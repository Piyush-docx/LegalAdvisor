import json
from pathlib import Path

import pytest

from src.retrieval import chunking as ch
from src.retrieval.chunking import Chunk, chunk_blocks, chunk_document, extract_blocks

FIXTURES = Path(__file__).parent / "fixtures"

ACT_HTML = """
<html><body><div class="akn-akomaNtoso">
<section class="akn-chapter"><h2>Chapter III - Deposits</h2>
<section class="akn-section" id="section_11"><h3><a href="/doc/1/">11.</a> Security deposit.</h3>
<section class="akn-subsection"><span class="akn-num">(1)</span><span class="akn-content"><span class="akn-p">Save an agreement to the contrary, it shall be unlawful to charge a security deposit in excess of three times the monthly rent.</span></span></section>
<section class="akn-subsection"><span class="akn-num">(2)</span><span class="akn-content"><span class="akn-p">The security deposit shall be refunded to the tenant within one month after vacation of the premises.</span></span></section>
</section>
<section class="akn-section" id="section_12"><h3>12. Repairs.</h3>
<section class="akn-subsection"><span class="akn-content"><span class="akn-p">The landlord shall carry out structural repairs and the tenant shall carry out day to day repairs of the premises.</span></span></section>
</section></section></div></body></html>
"""


def judgment_html(n_facts=3):
    para = "The appellant states that the cheque was dishonoured by the bank for insufficient funds and a notice was issued. "
    facts = "".join(f'<p data-structure="Facts">{para * 3} Paragraph {i}.</p>' for i in range(n_facts))
    return f"""
    <h2 class="doc_title">A vs B on 1 January, 2020</h2><h3 class="doc_author">Author: X</h3>
    <pre id="pre_1">IN THE HIGH COURT   \n\n    cause title</pre>
    {facts}
    <p data-structure="Precedent">In Dashrath Rupsingh Rathod the Supreme Court held that jurisdiction lies where the cheque is dishonoured.</p>
    <p data-structure="Conclusion">The appeal is dismissed and the conviction under Section 138 is upheld by this Court.</p>
    <p>12</p><p>Page 3 of 10</p>
    <p>Short.</p>
    """


def test_act_sections_become_one_chunk_each_with_number_and_title():
    chunks = chunk_document(ACT_HTML)

    assert len(chunks) == 2  # chapter heading alone is not a chunk; sub-sections stay inside their section
    first = chunks[0]
    assert first.text.startswith("11. Security deposit.")
    assert "(1) Save an agreement" in first.text and "(2) The security deposit shall be refunded" in first.text
    assert first.label == "11. Security deposit."
    assert chunks[1].text.startswith("12. Repairs.") and "security deposit" not in chunks[1].text


def test_act_sections_are_never_merged_even_when_tiny():
    html = "".join(
        f'<section class="akn-section"><h3>{i}. Heading {i}.</h3><section><span>Provision number {i} of the statute text here.</span></section></section>'
        for i in range(1, 4)
    )
    assert [c.label for c in chunk_document(html)] == ["1. Heading 1.", "2. Heading 2.", "3. Heading 3."]


def test_long_act_section_is_split_and_every_part_keeps_its_title():
    sentence = "The tenant shall pay the rent on or before the seventh day of each month. "
    html = f'<section class="akn-section"><h3>9. Payment of rent.</h3><section><span>{sentence * 60}</span></section></section>'

    chunks = chunk_document(html, size=500, overlap=60)

    assert len(chunks) > 3
    assert chunks[0].text.startswith("9. Payment of rent.")
    assert all("Payment of rent" in c.text for c in chunks)
    assert all(c.label == "9. Payment of rent." for c in chunks)


def test_judgment_blocks_keep_labels_drop_noise_and_keep_reasoning():
    blocks = extract_blocks(judgment_html())
    labels = [label for label, _ in blocks]
    texts = " ".join(t for _, t in blocks)

    assert "Facts" in labels and "Precedent" in labels and "Conclusion" in labels
    assert "Page 3 of 10" not in texts and "Short." not in texts  # page numbers and fragments dropped
    assert "A vs B on 1 January" not in texts                      # title/author headings are metadata


def test_same_label_paragraphs_are_packed_up_to_size_and_overlap_continues():
    chunks = chunk_document(judgment_html(n_facts=6), size=800, overlap=100)
    facts = [c for c in chunks if c.label == "Facts"]

    assert len(facts) >= 2
    assert all(len(c.text) <= 800 + 100 + 1 for c in facts)
    # overlap: the start of the next chunk repeats words from the end of the previous one
    tail_words = facts[0].text.split()[-5:]
    assert " ".join(tail_words[-3:]) in facts[1].text


def test_different_labels_are_not_merged():
    chunks = chunk_document(judgment_html())
    assert {c.label for c in chunks} >= {"Facts", "Precedent", "Conclusion"}
    assert not any("Precedent" in (c.label or "") and "appeal is dismissed" in c.text for c in chunks)


def test_hidden_text_spans_are_removed():
    html = '<p data-structure="Facts">Real sentence about the dispute and the parties involved here.<span class="hidden_text">PAGE 77 OF 90</span></p>'
    assert "PAGE 77" not in chunk_document(html)[0].text


def test_plain_text_fallback_splits_on_blank_lines():
    html = "<div>First paragraph of plain text that is long enough to keep.\n\nSecond paragraph of plain text that is long enough too.</div>"
    texts = [c.text for c in chunk_document(html, size=70, overlap=10)]
    assert len(texts) == 2 and texts[0].startswith("First paragraph")


def test_oversized_single_sentence_is_hard_split_and_never_exceeds_limits():
    html = f'<p data-structure="Facts">{"word " * 2000}</p>'
    chunks = chunk_document(html, size=400, overlap=50)
    assert len(chunks) > 5 and all(len(c.text) <= 400 + 50 + 2 for c in chunks)


def test_invalid_overlap_rejected_and_indices_sequential():
    with pytest.raises(ValueError):
        chunk_blocks([(None, "x" * 100)], size=100, overlap=100)
    chunks = chunk_document(judgment_html(n_facts=6), size=800, overlap=100)
    assert [c.idx for c in chunks] == list(range(len(chunks)))


def test_real_judgment_fixture_chunks_with_bounded_sizes():
    doc = json.loads((FIXTURES / "document_response.json").read_text())["doc"]

    chunks = chunk_document(doc)

    assert 20 < len(chunks) < 400
    assert max(len(c.text) for c in chunks) < ch.DEFAULT_SIZE + ch.DEFAULT_OVERLAP + 100
    assert min(len(c.text) for c in chunks) >= ch.MIN_CHUNK_CHARS
    assert any(c.label == "CDiscource" for c in chunks)  # the reasoning is kept, unlike extract_substantive_text
