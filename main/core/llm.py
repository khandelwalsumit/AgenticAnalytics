"""VertexAI / Gemini LLM factory."""

from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI

from config.settings import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    GOOGLE_API_KEY,
)


def get_llm(
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ChatGoogleGenerativeAI:
    """Create a ChatGoogleGenerativeAI instance with API Key config."""
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=GOOGLE_API_KEY,
        temperature=temperature,
        top_p=top_p,
        max_output_tokens=max_tokens,
    )
