"""Eval runner for the legal-help pipeline.

    python3 -m evals.run --label baseline_asis --live          # first run: records IKanoon + rewrites (costs credit)
    python3 -m evals.run --label after_fixes --judge           # replay recordings, add LLM-judge scores
    python3 -m evals.run --label x --compare evals/results/baseline_asis.json
    python3 -m evals.run --ids q01,q26 --label smoke --live    # small smoke test

Replay is the default: IKanoon search/document responses and query rewrites come from
``evals/recordings/``. ``--live`` lets missing ones hit the network (and records them);
``--fresh-rewrite`` re-runs the rewrite LLM instead of replaying it. The router and the answer
LLM always run live; they are what is being evaluated. Every case runs against a throwaway
SQLite file, never the real legal.db.

``--pg-schema`` instead runs the whole run in ONE throwaway schema on the DATABASE_URL PostgreSQL (dropped at the
end), so stored documents, chunks and answers carry over between cases and the tiers are exercised. ``--passes 2``
runs every case twice: pass 2 asks the same questions again and should be served from the store
(ids become "q01@2"). Needs EMBEDDING_API_KEY for the tiers; without it everything takes the cold path.

Judge calibration: score ~20 answers by hand, compare with the judge's rubric flags, and only
trust judge numbers once agreement is high.
"""

import argparse
from collections import Counter
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# Never touch the real database: set before any src module is imported.
_TMP = tempfile.mkdtemp(prefix="legal_eval_")
os.environ["DATABASE_PATH"] = os.path.join(_TMP, "boot.db")
PG_MODE = "--pg-schema" in sys.argv
if PG_MODE:
    # A throwaway schema inside the real database; the real tables are never touched.
    import uuid

    os.environ["DB_SCHEMA"] = f"eval_{uuid.uuid4().hex[:10]}"
    os.environ["INDEX_SYNC"] = "1"  # finish background indexing before the next case
    if not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
        sys.exit("--pg-schema needs a postgres DATABASE_URL in .env")
else:
    os.environ.pop("DATABASE_URL", None)

import src.db as db  # noqa: E402
import src.pipeline as pipeline  # noqa: E402
import src.retrieval.context as retrieval_context  # noqa: E402
from evals import checks  # noqa: E402
from evals.judge import JUDGE_MODEL, JudgeDailyLimit, JudgeError, judge_case  # noqa: E402
from evals.recorder import Recorder, RecordingMissing  # noqa: E402
from src.session import default_session_store  # noqa: E402

DATASET = ROOT / "evals" / "dataset.jsonl"
RESULTS = ROOT / "evals" / "results"
INFORMATIONAL_CHECKS = {"ends_cleanly"}

_REAL_SEARCH = retrieval_context.search_ikanoon
_REAL_FETCH = retrieval_context.fetch_document
_REAL_REWRITE = pipeline.rewrite_query
_REAL_CLASSIFY = pipeline.classify_intent
_REAL_EXPLAIN = pipeline.explain_with_llm
_REAL_COMPLETE = None  # set lazily: src.generation.generate.complete


def load_dataset(ids: set[str] | None, category: str | None, limit: int | None) -> list[dict]:
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    if ids:
        rows = [r for r in rows if r["id"] in ids]
    if category:
        rows = [r for r in rows if r["category"] == category]
    return rows[:limit] if limit else rows


class DailyQuotaExhausted(Exception):
    """Provider says the per-day quota is gone; retrying today is pointless."""


def _is_daily_quota(exc: Exception) -> bool:
    text = repr(exc).lower().replace("_", "").replace(" ", "")
    return any(marker in text for marker in ("perday", "tokensperday", "dailylimit", "(tpd)"))


def _is_rate_limit(exc: Exception) -> bool:
    text = repr(exc).lower()
    return any(s in text for s in ("429", "resource_exhausted", "rate limit", "rate_limit", "quota"))


def run_turn(text: str, sid: str | None, recorder: Recorder, retries: int) -> dict:
    import src.generation.generate as generate_module

    real_complete = generate_module.complete
    state = {"intent": None, "llm": [], "answer_models": []}

    def complete(task, prompt, *a, **k):
        result = real_complete(task, prompt, *a, **k)
        if task == "answer":
            state["answer_models"].append(result.model)  # which provider really wrote the answer
        return result

    def classify(*a, **k):
        result = _REAL_CLASSIFY(*a, **k)
        state["intent"] = result.name
        return result

    def explain(*a, **k):
        result = _REAL_EXPLAIN(*a, **k)
        state["llm"].append(result)
        return result

    out = {"user": text, "answer": "", "session_id": sid, "error": None, "missing": False,
           "attempts": 0, "retry_errors": []}
    for attempt in range(retries + 1):
        out["attempts"] = attempt + 1
        state["intent"], state["llm"], state["answer_models"] = None, [], []
        before = recorder.snapshot()
        start = time.perf_counter()
        try:
            with ExitStack() as stack:
                stack.enter_context(patch("src.retrieval.context.search_ikanoon", recorder.wrap_search(_REAL_SEARCH)))
                stack.enter_context(patch("src.retrieval.context.fetch_document", recorder.wrap_fetch(_REAL_FETCH)))
                stack.enter_context(patch("src.pipeline.rewrite_query", recorder.wrap_rewrite(_REAL_REWRITE)))
                stack.enter_context(patch("src.pipeline.classify_intent", classify))
                stack.enter_context(patch("src.pipeline.explain_with_llm", explain))
                stack.enter_context(patch("src.generation.generate.complete", complete))
                result = pipeline.answer_question(text, session_id=sid)
            out["answer"] = str(result)
            out["session_id"] = result.session_id
            out["error"] = None
            break
        except RecordingMissing as exc:
            out["error"], out["missing"] = str(exc), True
            break
        except Exception as exc:  # noqa: BLE001
            out["error"] = repr(exc)
            if _is_daily_quota(exc):
                out["daily_quota"] = True
                break
            if attempt < retries and _is_rate_limit(exc):
                out["retry_errors"].append(repr(exc)[:200])
                time.sleep(20 * (attempt + 1))
                continue
            break
    out["latency_ms"] = int((time.perf_counter() - start) * 1000)  # final attempt only (what a user would wait)
    after = recorder.snapshot()
    out["ikanoon_calls"] = sum(after[k] - before[k] for k in after)
    out["intent"] = state["intent"]
    llm = state["llm"]
    out["answer_model"] = state["answer_models"][-1] if state["answer_models"] else None
    out["stop_reason"] = llm[-1].stop_reason if llm else None
    out["tokens_in"] = sum(a.usage.input_tokens for a in llm)
    out["tokens_out"] = sum(a.usage.output_tokens for a in llm)
    return out


def run_case(case: dict, recorder: Recorder, retries: int, use_judge: bool) -> dict:
    if not PG_MODE:  # PostgreSQL mode keeps one schema for the whole run so stored data carries over
        path = os.path.join(_TMP, f"{case['id']}.db")
        db.DB_PATH = path
        db.init_db(path)
    with db.transaction() as conn:
        log_mark = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM query_logs").fetchone()["m"]

    turns, sid = [], None
    for text in case["turns"]:
        turn = run_turn(text, sid, recorder, retries)
        sid = turn["session_id"]
        turns.append(turn)
        if turn["error"]:
            break

    final = turns[-1]
    if final.get("daily_quota"):
        raise DailyQuotaExhausted(final["error"])
    result = {
        "id": case["id"], "category": case["category"], "behavior": case["behavior"],
        "status": "ok", "turns": [{k: v for k, v in t.items() if k != "session_id"} for t in turns],
    }
    if final["error"]:
        result["status"] = "skipped" if final["missing"] else "error"
        result["reason"] = final["error"]
        return result

    context, citations = "", []
    if final["intent"] != "CHITCHAT":
        session = default_session_store.get(sid)
        if session:
            context = session.last_context_text or ""
            citations = session.last_citations
    titles = [c.title for c in citations]
    urls = [c.url for c in citations]

    case_checks = checks.run_checks(case, final["answer"], context, titles, urls, final)
    body = checks.split_answer(final["answer"])["body"]
    result.update({
        "final_answer": final["answer"],
        "context_chars": len(context),
        "citation_titles": titles,
        "checks": case_checks,
        "ungrounded_sections": checks.ungrounded_sections(body, context) if case["behavior"] == "answer" else [],
        "first_source_rank": (
            checks.first_context_rank(case["expected_sources_any"], context)
            if case["behavior"] == "answer" and case.get("expected_sources_any") else None
        ),
        "ikanoon_calls_total": sum(t["ikanoon_calls"] for t in turns),
        "tokens_in": sum(t["tokens_in"] for t in turns),
        "tokens_out": sum(t["tokens_out"] for t in turns),
        "any_truncated": any(t["stop_reason"] == "MAX_TOKENS" for t in turns),
        "passed": all(v for k, v in case_checks.items() if v is not None and k not in INFORMATIONAL_CHECKS),
    })

    with db.transaction() as conn:
        logs = conn.execute(
            "SELECT was_cached, guardrails FROM query_logs WHERE id > ?", (log_mark,)
        ).fetchall()
    result["cache_hits"], result["logged_queries"] = sum(1 for r in logs if r["was_cached"]), len(logs)
    flags = [f for r in logs for f in (r["guardrails"] or "").split(",") if f.startswith("tier:")]
    result["tiers"] = flags

    if use_judge:
        try:
            result["judge"] = judge_case(case, final["answer"], context)
        except JudgeDailyLimit as exc:
            result["judge"] = {"error": str(exc)}
            result["judge_limit_reached"] = True
        except JudgeError as exc:
            result["judge"] = {"error": str(exc)}
    return result


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    return int(statistics.quantiles(xs, n=100, method="inclusive")[p - 1])


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if r["status"] == "ok"]
    check_names = sorted({k for r in ok for k, v in r["checks"].items() if v is not None})
    per_check = {}
    for name in check_names:
        vals = [r["checks"][name] for r in ok if r["checks"].get(name) is not None]
        per_check[name] = {"passed": sum(vals), "applicable": len(vals)}

    by_cat: dict[str, list[bool]] = {}
    for r in ok:
        by_cat.setdefault(r["category"], []).append(r["passed"])

    answer_cases = [r for r in ok if r["behavior"] == "answer"]
    retr = [r for r in answer_cases if r["checks"].get("expected_source_retrieved") is not None]
    rr = [(1 / r["first_source_rank"]) if r["first_source_rank"] else 0 for r in retr]
    gen = [r for r in ok if r["tokens_out"]]
    judged = [r["judge"] for r in ok if r.get("judge") and "error" not in r["judge"]]
    ans_judged = [r["judge"] for r in answer_cases if r.get("judge") and "error" not in r["judge"]]

    return {
        "cases": len(results), "ok": len(ok),
        "skipped_not_recorded": sum(r["status"] == "skipped" for r in results),
        "errors": sum(r["status"] == "error" for r in results),
        "pass_rate": _mean([r["passed"] for r in ok]),
        "per_check": per_check,
        "pass_rate_by_category": {c: _mean(v) for c, v in sorted(by_cat.items())},
        "latency_ms_p50": _pct([r["turns"][-1]["latency_ms"] for r in ok], 50),
        "latency_ms_p95": _pct([r["turns"][-1]["latency_ms"] for r in ok], 95),
        "ikanoon_calls_per_answer_case": _mean([r["ikanoon_calls_total"] for r in answer_cases]),
        "gen_tokens_in_mean": _mean([r["tokens_in"] for r in gen]),
        "gen_tokens_out_mean": _mean([r["tokens_out"] for r in gen]),
        "truncation_rate": _mean([r["any_truncated"] for r in gen]),
        "retrieval_hit_rate": _mean([r["checks"]["expected_source_retrieved"] for r in retr]),
        "retrieval_mrr": _mean(rr),
        "cache_hit_rate": (
            round(sum(r["cache_hits"] for r in ok) / max(1, sum(r["logged_queries"] for r in ok)), 3)
        ),
        "judge_faithfulness_mean": _mean([j.get("faithfulness") for j in ans_judged]),
        "judge_rubric_coverage_mean": _mean([j.get("rubric_coverage") for j in judged]),
        "judge_personalised_advice_count": sum(j.get("personalised_advice", False) for j in judged),
        "judge_scored": len(judged),
        "tiers": dict(Counter(t for r in ok for t in r.get("tiers", []))),
        "answer_models": dict(Counter(r["turns"][-1].get("answer_model") for r in ok if r["turns"][-1].get("answer_model"))),
    }


def print_summary(summary: dict, results: list[dict]) -> None:
    s = summary
    print(f"\n=== {s['ok']}/{s['cases']} cases ran | skipped (not recorded): {s['skipped_not_recorded']} | errors: {s['errors']}")
    print(f"overall pass rate (deterministic): {s['pass_rate']}")
    print("per check:")
    for name, v in s["per_check"].items():
        print(f"  {name:28s} {v['passed']}/{v['applicable']}")
    print("by category:", s["pass_rate_by_category"])
    for key in ("latency_ms_p50", "latency_ms_p95", "ikanoon_calls_per_answer_case", "gen_tokens_in_mean",
                "gen_tokens_out_mean", "truncation_rate", "retrieval_hit_rate", "retrieval_mrr",
                "cache_hit_rate", "judge_faithfulness_mean", "judge_rubric_coverage_mean",
                "judge_personalised_advice_count", "tiers", "answer_models"):
        print(f"{key:34s} {s[key]}")
    failed = [r["id"] for r in results if r["status"] == "ok" and not r["passed"]]
    print("failed cases:", ", ".join(failed) or "none")


def print_compare(old: dict, new: dict, old_results: list[dict], new_results: list[dict]) -> None:
    print("\n=== compare vs", old.get("label"))
    for key, nv in new["summary"].items():
        ov = old["summary"].get(key)
        if isinstance(nv, (int, float)) and isinstance(ov, (int, float)) and nv != ov:
            print(f"  {key:34s} {ov} -> {nv}")
    old_pass = {r["id"]: r.get("passed") for r in old_results if r["status"] == "ok"}
    new_pass = {r["id"]: r.get("passed") for r in new_results if r["status"] == "ok"}
    regressed = [i for i in new_pass if old_pass.get(i) is True and new_pass[i] is False]
    fixed = [i for i in new_pass if old_pass.get(i) is False and new_pass[i] is True]
    print("  regressed:", ", ".join(regressed) or "none")
    print("  fixed:    ", ", ".join(fixed) or "none")


def git_info() -> dict:
    def run(*cmd):
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": run("git", "rev-parse", "--short", "HEAD"), "dirty": bool(run("git", "status", "--porcelain"))}


def model_config() -> dict:
    from src import llm
    return {**llm.describe(), "judge": JUDGE_MODEL}


def save_results(label, args, recorder, results, partial: bool, halted: bool = False):
    """Write the results file. Called after every case (partial=True) so a stopped or crashed run keeps what it has."""
    order = {c["id"]: n for n, c in enumerate(load_dataset(None, None, None))}

    def position(r):  # "q01@2" sorts after every pass-1 case
        base, _, n = r["id"].partition("@")
        return (int(n or 1), order.get(base, 10**6))

    ordered = sorted(results, key=position)
    summary = summarize(ordered)
    summary["halted_on_daily_quota"] = halted
    payload = {
        "label": label, "partial": partial, "timestamp": datetime.now(timezone.utc).isoformat(), "git": git_info(),
        "config": model_config(), "mode": {"live": args.live, "fresh_rewrite": args.fresh_rewrite, "judge": args.judge},
        "network_calls_made": {"ikanoon_live": recorder.live_calls, "ikanoon_logical": recorder.calls},
        "summary": summary, "cases": ordered,
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{label}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return summary, out


def _drop_schema() -> None:
    import psycopg

    try:
        db.close_pool()
        with psycopg.connect(db.direct_url(os.environ["DATABASE_URL"]), autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{os.environ["DB_SCHEMA"]}" CASCADE')
        print(f"dropped throwaway schema {os.environ['DB_SCHEMA']}")
    except Exception as exc:  # noqa: BLE001
        print(f"!! could not drop schema {os.environ['DB_SCHEMA']}: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default=datetime.now().strftime("run_%Y%m%d_%H%M%S"))
    ap.add_argument("--ids", help="comma-separated case ids")
    ap.add_argument("--category")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--live", action="store_true", help="allow network calls for anything not recorded (costs IKanoon credit)")
    ap.add_argument("--fresh-rewrite", action="store_true", help="re-run the rewrite LLM instead of replaying it")
    ap.add_argument("--judge", action="store_true", help="add LLM-judge scores (Groq)")
    ap.add_argument("--resume", action="store_true",
                    help="continue an existing --label results file: keep its ok cases, run the rest")
    ap.add_argument("--pg-schema", action="store_true",
                    help="run in a throwaway PostgreSQL schema (tiers 1-2 and follow-ups become testable)")
    ap.add_argument("--passes", type=int, default=1, help="run every case this many times (pass 2+ ids are 'q01@2')")
    ap.add_argument("--compare", help="path to a previous results JSON")
    ap.add_argument("--sleep", type=float, default=0, help="seconds to pause between cases (provider rate limits)")
    ap.add_argument("--retries", type=int, default=2, help="retries per turn on rate-limit errors")
    args = ap.parse_args()

    cases = load_dataset(set(args.ids.split(",")) if args.ids else None, args.category, args.limit)
    recorder = Recorder(live=args.live, fresh_rewrite=args.fresh_rewrite)
    if args.passes > 1:
        cases = cases + [{**c, "id": f"{c['id']}@{n}"} for n in range(2, args.passes + 1) for c in cases]
    if PG_MODE:
        import atexit

        db.init_db()
        atexit.register(_drop_schema)
    out = RESULTS / f"{args.label}.json"
    kept: dict[str, dict] = {}
    if args.resume and out.exists():
        kept = {r["id"]: r for r in json.loads(out.read_text())["cases"] if r["status"] == "ok"}
        print(f"resuming: keeping {len(kept)} finished cases from {out.name}")
    results = list(kept.values())
    halted = False
    for i, case in enumerate(cases, 1):
        if case["id"] in kept:
            continue
        try:
            r = run_case(case, recorder, args.retries, args.judge)
            if r.pop("judge_limit_reached", False):
                print("!! judge model hit its daily limit: judging is switched off for the rest of this run")
                args.judge = False
        except DailyQuotaExhausted as exc:
            print(f"\n!! daily quota exhausted at {case['id']} - saving progress; rerun with --resume tomorrow\n   {str(exc)[:160]}")
            halted = True
            break
        results.append(r)
        save_results(args.label, args, recorder, results, partial=True)
        flag = {"ok": "PASS" if r.get("passed") else "FAIL", "skipped": "SKIP", "error": "ERR "}[r["status"]]
        extra = r.get("reason", "")[:90] if r["status"] != "ok" else ""
        print(f"[{i}/{len(cases)}] {case['id']:5s} {case['category']:12s} {flag} "
              f"{r['turns'][-1].get('latency_ms', 0) / 1000:.1f}s {extra}", flush=True)
        if args.sleep:
            time.sleep(args.sleep)

    summary, out = save_results(args.label, args, recorder, results, partial=False, halted=halted)
    print_summary(summary, results)
    print(f"IKanoon calls: logical={recorder.calls} live(billed)={recorder.live_calls}")
    print("saved ->", out)

    if args.compare:
        old = json.loads(Path(args.compare).read_text())
        print_compare(old, json.loads(out.read_text()), old["cases"], results)


if __name__ == "__main__":
    main()
