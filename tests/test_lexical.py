from src.retrieval.chunking import Chunk
from src.retrieval.lexical import BM25, query_terms, rank_chunks, tokenize


def chunks(*texts):
    return [Chunk(idx=i, text=t) for i, t in enumerate(texts)]


def test_query_terms_parse_ikanoon_syntax_and_phrases():
    terms, phrases = query_terms('"security deposit" ANDD tenancy ANDD refund doctypes: laws')

    assert phrases == ["security deposit"]
    assert sorted(terms) == ["deposit", "refund", "security", "tenancy"]
    assert "andd" not in terms and "doctypes" not in terms and "laws" not in terms


def test_query_terms_include_question_words_without_stopwords():
    terms, _ = query_terms('"cheque bounce"', "What is the punishment for cheque bounce under Section 138?")
    assert "punishment" in terms and "138" in terms and "what" not in terms and "the" not in terms


def test_stemming_matches_simple_variants():
    assert tokenize("deposits refunded refunding evictions") == ["deposit", "refund", "refund", "eviction"]


def test_bm25_ranks_the_relevant_chunk_first():
    cs = chunks(
        "The security deposit shall be refunded to the tenant within one month after vacation.",
        "The Magistrate may pass a protection order in favour of the aggrieved person.",
        "Rent shall be paid on or before the seventh day of every month by the tenant.",
    )

    ranked = rank_chunks(cs, '"security deposit" ANDD refund', "deposit refund")

    assert ranked[0][0] is cs[0]
    assert all(score > 0 for _, score in ranked)


def test_phrase_match_gets_a_bonus():
    cs = chunks("a deposit was paid and security was provided by guard", "the security deposit was paid in advance")
    scores = BM25([c.text for c in cs]).scores(["security", "deposit"], ["security deposit"])
    assert scores[1] > scores[0]


def test_chunks_matching_nothing_are_dropped_and_top_k_respected():
    cs = chunks("alpha beta gamma delta", "unrelated epsilon words here", *[f"deposit number {i} deposit" for i in range(10)])

    ranked = rank_chunks(cs, "deposit", top_k=3)

    assert len(ranked) == 3 and all("deposit" in c.text for c, _ in ranked)
    assert rank_chunks(cs, "zzzz") == []


def test_empty_inputs_are_safe():
    assert rank_chunks([], "deposit") == []
    assert rank_chunks(chunks("some text here"), "") == []
