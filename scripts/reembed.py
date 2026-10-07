"""Re-embed stored vectors after changing the embedding model. Dry run by default.

    python3 scripts/reembed.py           # show what would change
    python3 scripts/reembed.py --apply   # do it (resumable; rerun if it stops)

See docs/embedding_model_switch.md for the full procedure.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src import embedding_migration as m  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="perform the re-embedding (default: dry run)")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    plan = m.make_plan()
    print(f"target embedding id : {plan.current_id}")
    print(f"vector column sizes : {plan.column_dims} (target {plan.target_dim})")
    print(f"rows to re-embed    : {plan.stale_rows} (about {plan.estimated_tokens:,} tokens)")
    if plan.needs_dimension_change:
        print("NOTE: the vector size differs, so existing vectors are cleared and rebuilt.")
    if plan.nothing_to_do:
        print("Nothing to do.")
        return
    if not args.apply:
        print("Dry run. Re-run with --apply to proceed.")
        return
    result = m.migrate(batch_size=args.batch_size)
    print("result:", result)
    if not result["completed"]:
        sys.exit("Stopped early (embedding service unavailable). Run again to resume.")


if __name__ == "__main__":
    main()
