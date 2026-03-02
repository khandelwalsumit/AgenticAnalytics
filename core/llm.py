"""Backward-compatible LLM import shim.

Prefer importing VertexAILLM from core.chat_model.
"""

from core.chat_model import VertexAILLM

__all__ = ["VertexAILLM"]
