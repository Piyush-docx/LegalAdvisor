from pydantic import BaseModel


class SearchDoc(BaseModel):
    tid: int
    title: str
    doctype: int
    docsource: str
    publishdate: str
    headline: str
    docsize: int
    numcites: int
    numcitedby: int
    catids: list[int] | None = None
    authorid: int | None = None
    author: str | None = None
    authorEncoded: str | None = None
    bench: list[int] | None = None
    fragment: bool | None = None


class SearchResult(BaseModel):
    docs: list[SearchDoc]
    found: str
    categories: list | None = None
    encodedformInput: str | None = None


class DocumentText(BaseModel):
    tid: int
    title: str
    docsource: str
    publishdate: str
    doc: str
    numcites: int
    numcitedby: int
    divtype: str | None = None
