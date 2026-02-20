"""VertexAI / Gemini LLM factory."""

from __future__ import annotations

from langchain_google_vertexai import ChatVertexAI

from config.settings import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    GOOGLE_CLOUD_LOCATION,
    GOOGLE_CLOUD_PROJECT,
)


def get_llm(
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ChatVertexAI:
    """Create a ChatVertexAI instance with custom endpoint config."""
    return ChatVertexAI(
        model_name=model,
        project=GOOGLE_CLOUD_PROJECT,
        location=GOOGLE_CLOUD_LOCATION,
        temperature=temperature,
        top_p=top_p,
        max_output_tokens=max_tokens,
    )
