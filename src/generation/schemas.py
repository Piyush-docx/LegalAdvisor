from pydantic import BaseModel


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class LLMAnswer(BaseModel):
    text: str
    stop_reason: str
    truncated: bool = False
    usage: Usage
