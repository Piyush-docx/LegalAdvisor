"""Keyword (BM25) ranking of chunks: free, instant, and needs no embedding API.

Used on the cold path to pick the best chunks from freshly fetched documents, and as the fallback
when the embedding service is unavailable. Queries come from the English search query produced by
the rewrite step, so Hinglish questions still match English legal text.
"""

import math
import re

_STOPWORDS = frozenset(
    "a an and are as at be been by can could did do does for from had has have how i if in into is it its may "
    "me my no not of on or our shall should so than that the their them then there these they this to under "
    "was we were what when where which who whom why will with would you your".split()
)
_OPERATOR_WORDS = frozenset({"andd", "and", "or", "not", "doctypes", "laws", "judgments"})
_QUOTED = re.compile(r'"([^"]+)"')


def _stem(word: str) -> str:
    """Conservative suffix stripping so 'deposits', 'evicted', 'eviction' style variants meet."""
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS and len(w) > 1]


def query_terms(search_query: str, question: str | None = None) -> tuple[list[str], list[str]]:
    """Return (terms, phrases) from an IKanoon-style query such as
    '"security deposit" ANDD tenancy ANDD refund doctypes:laws', plus the original question's words."""
    phrases = [p.lower() for p in _QUOTED.findall(search_query)]
    bare = _QUOTED.sub(" ", search_query)
    bare = re.sub(r"doctypes:\s*\w+", " ", bare, flags=re.IGNORECASE)
    words = [w for w in re.findall(r"[A-Za-z0-9]+", bare) if w.lower() not in _OPERATOR_WORDS]
    terms = tokenize(" ".join(words + phrases))
    if question:
        terms += tokenize(question)
    return list(dict.fromkeys(terms)), phrases


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.texts = [d.lower() for d in documents]
        self.tokens = [tokenize(d) for d in documents]
        self.lengths = [len(t) for t in self.tokens]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.doc_freq: dict[str, int] = {}
        for toks in self.tokens:
            for term in set(toks):
                self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
        self.counts = [self._count(t) for t in self.tokens]

    @staticmethod
    def _count(tokens: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        return counts

    def scores(self, terms: list[str], phrases: list[str] | None = None, phrase_bonus: float = 3.0) -> list[float]:
        n = len(self.tokens)
        out = []
        for i in range(n):
            score = 0.0
            for term in terms:
                tf = self.counts[i].get(term, 0)
                if not tf:
                    continue
                df = self.doc_freq[term]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                norm = 1 - self.b + self.b * (self.lengths[i] / self.avg_len if self.avg_len else 1)
                score += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
            for phrase in phrases or []:
                if phrase and phrase in self.texts[i]:
                    score += phrase_bonus
            out.append(score)
        return out


def rank_chunks(chunks, search_query: str, question: str | None = None, top_k: int = 8, min_score: float = 0.0):
    """Return [(chunk, score)] best first, dropping chunks that do not match any query term."""
    terms, phrases = query_terms(search_query, question)
    if not chunks or not (terms or phrases):
        return []
    scored = BM25([c.text for c in chunks]).scores(terms, phrases)
    ranked = sorted(zip(chunks, scored), key=lambda cs: cs[1], reverse=True)
    return [(c, s) for c, s in ranked if s > min_score][:top_k]
