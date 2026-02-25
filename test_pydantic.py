from pydantic import BaseModel, Field
from typing import Literal, Optional, List

class SlideElement(BaseModel):
    type: Literal["paragraph"] = Field(default="paragraph")

class SlideBlueprint(BaseModel):
    slide_number: int = Field(default=1, ge=1)
    section_type: str = Field(default="narrative")
    layout: Literal[
        "title_slide",
        "section_divider",
        "callout",
        "three_column",
        "table",
        "scorecard_table",
    ] = Field(default="callout")
    title: str = Field(default="")
    qa_note: Optional[str] = Field(default=None)
    elements: List[SlideElement] = Field(default_factory=list)

class FormattingDeckOutput(BaseModel):
    slides: List[SlideBlueprint] = Field(default_factory=list)

data = {
    "slides": [
        {'slide_number': 7, 'section_type': 'matrix', 'layout': None, 'title': None}
    ]
}

try:
    FormattingDeckOutput.model_validate(data, strict=True)
    print("Success with strict=True")
except Exception as e:
    print("Error with strict=True:", e)
