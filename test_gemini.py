from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from typing import Literal, Optional, List
import os

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

import config
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=config.GOOGLE_API_KEY)
structured_llm = llm.with_structured_output(FormattingDeckOutput)

try:
    print(structured_llm.invoke("Generate exactly this JSON: {\"slides\": [{\"slide_number\": 7, \"section_type\": \"matrix\"}]}"))
except Exception as e:
    print(e)
