"""Split an IKanoon document into retrieval chunks.

IKanoon documents come in three shapes, each chunked on its natural boundaries:
  * Acts (Akoma Ntoso): one chunk per legal section, never merged with its neighbours, and always
    starting with its number and title ("11. Security deposit. (1) ... (2) ..."). Sections too long for
    one chunk are split at sentences and each part repeats the heading.
  * Tagged judgments: <p>/<blockquote> blocks labelled Issue/Facts/CDiscource/Precedent/Conclusion...
    -> consecutive blocks with the same label are packed together up to `size` characters.
  * Anything else: plain text split on blank lines.
Unlike extract_substantive_text (which keeps only Issue/Facts/Conclusion), the judges' reasoning is kept.
Page numbers, the "hidden_text" artefacts and tiny fragments are dropped.
"""

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup

DEFAULT_SIZE = 1200
DEFAULT_OVERLAP = 150
MIN_CHUNK_CHARS = 40

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_PAGE_NOISE = re.compile(r"^(page\s*)?\d+(\s*(of|/)\s*\d+)?$", re.IGNORECASE)


@dataclass
class Chunk:
    idx: int
    text: str
    label: str | None = None  # data-structure tag for judgments, section heading for Acts


def _norm(text: str) -> str:
    return " ".join(text.split())


_HEADINGS = ["h2", "h3", "h4"]


def _own_heading(section) -> str | None:
    h = section.find(_HEADINGS, recursive=False)
    return _norm(h.get_text(" "))[:120] if h else None


def extract_blocks(raw_html: str) -> list[tuple[str | None, str]]:
    """Return [(label, text)] blocks in document order."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    for span in soup.find_all("span", class_="hidden_text"):
        span.decompose()

    blocks: list[tuple[str | None, str]] = []

    sections = soup.find_all("section")
    # Akoma Ntoso Act: the unit is the innermost section that carries its own heading. Chapters
    # contain headed sections and are skipped; sub-sections "(1)", "(2)" have no heading and stay
    # inside their section.
    headed = [s for s in sections if _own_heading(s) and not any(_own_heading(d) for d in s.find_all("section"))]
    if headed:
        for sec in headed:
            blocks.append((_own_heading(sec), _norm(sec.get_text(" "))))
    elif sections:  # sectioned but without headings: fall back to the leaf sections
        for sec in sections:
            if not sec.find("section"):
                blocks.append((None, _norm(sec.get_text(" "))))
    elif soup.find(["p", "blockquote"]):  # tagged judgment
        wanted = soup.find_all(["p", "blockquote", "pre"])
        chosen = [el for el in wanted if not any(parent in wanted for parent in el.parents)]
        for el in chosen:
            blocks.append((el.get("data-structure"), _norm(el.get_text(" "))))
    else:  # fallback: plain text
        for part in re.split(r"\n\s*\n", soup.get_text("\n")):
            blocks.append((None, _norm(part)))

    return [(label, text) for label, text in blocks if len(text) >= MIN_CHUNK_CHARS and not _PAGE_NOISE.match(text)]


def _split_long(text: str, size: int) -> list[str]:
    """Split one oversized block at sentence boundaries, hard-splitting only if a sentence is too long."""
    pieces, current = [], ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > size:  # a single enormous sentence: cut at whitespace near `size`
            cut = sentence.rfind(" ", 0, size) or size
            cut = cut if cut > size // 2 else size
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > size:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, overlap: int) -> str:
    """Last ~`overlap` characters, starting at a word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1:] if space != -1 else tail


def chunk_blocks(
    blocks: list[tuple[str | None, str]], size: int = DEFAULT_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    merge_labels = {"Issue", "Facts", "CDiscource", "Precedent", "Conclusion", "PetArg", "RespArg"}
    chunks: list[Chunk] = []

    def emit(text: str, label: str | None) -> None:
        text = text.strip()
        if len(text) >= MIN_CHUNK_CHARS:
            chunks.append(Chunk(idx=len(chunks), text=text, label=label))

    current, current_label = "", None
    for label, text in blocks:
        mergeable = label in merge_labels or label is None
        if len(text) > size:
            if current:
                emit(current, current_label)
                current = ""
            carry = ""
            for n, piece in enumerate(_split_long(text, size)):
                if n and label and label not in merge_labels:
                    piece = f"{label} (continued) {piece}"  # keep the section title on every part of an Act section
                emit(f"{carry} {piece}".strip() if carry else piece, label)
                carry = _tail(piece, overlap)
            continue
        if current and mergeable and label == current_label and len(current) + 1 + len(text) <= size:
            current = f"{current} {text}"
            continue
        if current:
            emit(current, current_label)
            overlap_text = _tail(current, overlap) if (mergeable and label == current_label) else ""
            current = f"{overlap_text} {text}".strip() if overlap_text else text
        else:
            current = text
        current_label = label
    if current:
        emit(current, current_label)
    return chunks


def chunk_document(raw_html: str, size: int = DEFAULT_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[Chunk]:
    return chunk_blocks(extract_blocks(raw_html), size=size, overlap=overlap)
