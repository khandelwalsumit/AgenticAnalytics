"""Custom Vertex AI chat model wrapper for company R2D2-authenticated runtime.

Strict mode:
- Uses Vertex AI generative model path only.
- Uses core.auth.authenticate_vertexai() for auth bootstrap.
- No ChatGoogleGenerativeAI fallback.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from config import (
    BACKOFF_MAX_DELAY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from core.auth import authenticate_vertexai

logger = logging.getLogger(__name__)

try:
    from google.api_core.exceptions import ResourceExhausted, TooManyRequests

    _RATE_LIMIT_EXCEPTIONS: tuple[type[Exception], ...] = (TooManyRequests, ResourceExhausted)
except Exception:
    _RATE_LIMIT_EXCEPTIONS = ()

from vertexai.generative_models import (
    Content,
    FunctionDeclaration,
    GenerationConfig,
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    Part,
    SafetySetting,
    Tool as VertexTool,
)

_VERTEX_AVAILABLE = True
_VERTEX_IMPORT_ERROR: Exception | None = None

_MODEL_INIT_LOCK = threading.Lock()

_SAFETY_SETTINGS = [
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=HarmBlockThreshold.BLOCK_NONE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=HarmBlockThreshold.BLOCK_NONE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=HarmBlockThreshold.BLOCK_NONE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=HarmBlockThreshold.BLOCK_NONE,
    ),
]


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove keys unsupported by Vertex schema/function declarations."""
    blocked_keys = {"additionalProperties", "title", "$defs", "definitions", "$ref"}
    cleaned = {k: v for k, v in schema.items() if k not in blocked_keys}

    props = cleaned.get("properties")
    if isinstance(props, dict):
        cleaned["properties"] = {
            key: _clean_schema(value) if isinstance(value, dict) else value
            for key, value in props.items()
        }

    items = cleaned.get("items")
    if isinstance(items, dict):
        cleaned["items"] = _clean_schema(items)

    return cleaned


def _is_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "401",
        "403",
        "unauthenticated",
        "permission denied",
        "invalid credentials",
        "token",
        "auth",
    )
    return any(marker in text for marker in markers)


class VertexAIChatModel(BaseChatModel):
    """LangChain BaseChatModel adapter for Vertex AI with tool calling."""

    model_name: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    top_p: float = DEFAULT_TOP_P

    system_instruction: Optional[str] = None
    response_schema: Optional[Dict[str, Any]] = None
    response_mime_type: Optional[str] = None

    tools: List[BaseTool] = Field(default_factory=list)
    vertex_tools: List[Any] = Field(default_factory=list)

    gen_model: Optional[Any] = None

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    def __init__(self, **data: Any):
        super().__init__(**data)
        self._initialize_vertex_model(force_auth=False)

    def _ensure_vertex_sdk(self) -> None:
        if not _VERTEX_AVAILABLE:
            raise RuntimeError(
                "vertexai SDK is required for this environment but could not be imported. "
                f"Import error: {_VERTEX_IMPORT_ERROR}"
            )

    def _initialize_vertex_model(self, force_auth: bool) -> None:
        self._ensure_vertex_sdk()
        authenticate_vertexai(force=force_auth)
        with _MODEL_INIT_LOCK:
            self.gen_model = GenerativeModel(
                self.model_name,
                system_instruction=self.system_instruction,
            )

    def _langchain_tool_to_vertex_fd(self, tool: BaseTool) -> Any:
        if getattr(tool, "args_schema", None):
            params = _clean_schema(tool.args_schema.model_json_schema())
        else:
            params = {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input to the tool"},
                },
                "required": ["input"],
            }

        return FunctionDeclaration(
            name=tool.name,
            description=tool.description or "Tool function",
            parameters=params if params.get("properties") else {},
        )

    def _convert_tools_to_vertex_format(self, tools: List[BaseTool]) -> List[Any]:
        declarations = [self._langchain_tool_to_vertex_fd(tool) for tool in tools]
        return [VertexTool(function_declarations=declarations)] if declarations else []

    @staticmethod
    def _tool_message_to_part(message: ToolMessage) -> tuple[Any, str]:
        """Convert a single ToolMessage to a Vertex function_response Part.

        Returns (Part, tool_name) so callers can log if needed.
        """
        tool_output: dict[str, Any]
        if isinstance(message.content, str):
            try:
                parsed = json.loads(message.content)
                tool_output = parsed if isinstance(parsed, dict) else {"result": parsed}
            except json.JSONDecodeError:
                tool_output = {"result": message.content}
        elif isinstance(message.content, dict):
            tool_output = message.content
        else:
            tool_output = {"result": message.content}

        tool_name = message.name or message.tool_call_id or "tool_result"
        return Part.from_function_response(name=tool_name, response=tool_output), tool_name

    def _convert_messages_to_vertex_format(
        self,
        messages: List[BaseMessage],
    ) -> tuple[List[Any], Optional[str]]:
        """Convert LangChain messages to Vertex AI Content objects.

        Critical: Vertex AI requires that after a model turn with N function_call
        parts, the next Content must contain exactly N function_response parts in
        a **single** Content block.  LangGraph emits one ToolMessage per tool call,
        so we must group consecutive ToolMessages into one Content.
        """
        contents: list[Any] = []
        extracted_system_instruction: Optional[str] = None

        idx = 0
        n = len(messages)

        while idx < n:
            message = messages[idx]

            if isinstance(message, SystemMessage):
                sys_text = str(message.content)
                extracted_system_instruction = (
                    sys_text
                    if not extracted_system_instruction
                    else f"{extracted_system_instruction}\n{sys_text}"
                )
                idx += 1
                continue

            if isinstance(message, HumanMessage):
                contents.append(Content(role="user", parts=[Part.from_text(str(message.content))]))
                idx += 1
                continue

            if isinstance(message, AIMessage):
                ai_parts: list[Any] = []

                # Only add a text part when the model actually produced text.
                # Empty-string content (common when the model only calls tools)
                # must be omitted — Vertex rejects empty text parts.
                text = str(message.content) if message.content else ""
                if text.strip():
                    ai_parts.append(Part.from_text(text))

                for tool_call in getattr(message, "tool_calls", []) or []:
                    tc_name = tool_call.get("name") if isinstance(tool_call, dict) else getattr(tool_call, "name", "")
                    tc_args = tool_call.get("args", {}) if isinstance(tool_call, dict) else getattr(tool_call, "args", {})
                    if tc_name:
                        ai_parts.append(Part.from_dict({
                            "function_call": {"name": tc_name, "args": tc_args or {}},
                        }))

                if ai_parts:
                    contents.append(Content(role="model", parts=ai_parts))
                idx += 1
                continue

            if isinstance(message, ToolMessage):
                # --- Core fix: batch ALL consecutive ToolMessages into one
                # Content so the function_response count matches the preceding
                # model turn's function_call count. ---
                tool_parts: list[Any] = []
                while idx < n and isinstance(messages[idx], ToolMessage):
                    part, _ = self._tool_message_to_part(messages[idx])
                    tool_parts.append(part)
                    idx += 1

                if tool_parts:
                    contents.append(Content(role="tool", parts=tool_parts))
                continue

            # Unknown message type — skip gracefully
            idx += 1

        return contents, extracted_system_instruction

    def _call_with_backoff(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        if BACKOFF_MAX_DELAY <= 0 or not _RATE_LIMIT_EXCEPTIONS:
            return func(*args, **kwargs)

        delay = 1.0
        for attempt in range(10):
            try:
                return func(*args, **kwargs)
            except _RATE_LIMIT_EXCEPTIONS as exc:
                if attempt >= 9:
                    raise RuntimeError(f"Rate limit exceeded after retries: {exc}") from exc
                actual_delay = delay * (0.7 + random.random() * 0.3)
                logger.warning(
                    "Rate limit hit (attempt %d/10). Retrying in %.1fs",
                    attempt + 1,
                    actual_delay,
                )
                time.sleep(actual_delay)
                delay = min(delay * 2, float(BACKOFF_MAX_DELAY))

    def _build_generation_config(
        self,
        stop: Optional[List[str]],
        response_schema: Optional[Dict[str, Any]] = None,
        response_mime_type: Optional[str] = None,
    ) -> Any:
        cfg: dict[str, Any] = {
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
            "top_p": self.top_p,
        }
        if stop:
            cfg["stop_sequences"] = stop
        if response_schema:
            cfg["response_schema"] = response_schema
            cfg["response_mime_type"] = response_mime_type or "application/json"
        return GenerationConfig(**cfg)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        _auth_retry: bool = False,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            if self.gen_model is None:
                self._initialize_vertex_model(force_auth=False)

            contents, extracted_system_instruction = self._convert_messages_to_vertex_format(messages)
            active_system_instruction = extracted_system_instruction or self.system_instruction

            response_schema = kwargs.get("response_schema", self.response_schema)
            response_mime_type = kwargs.get("response_mime_type", self.response_mime_type)
            generation_config = self._build_generation_config(stop, response_schema, response_mime_type)

            call_kwargs: dict[str, Any] = {
                "generation_config": generation_config,
                "safety_settings": _SAFETY_SETTINGS,
            }
            if self.vertex_tools:
                call_kwargs["tools"] = self.vertex_tools

            model = self.gen_model
            if active_system_instruction and active_system_instruction != self.system_instruction:
                model = GenerativeModel(self.model_name, system_instruction=active_system_instruction)

            response = self._call_with_backoff(model.generate_content, contents, **call_kwargs)

            if not getattr(response, "candidates", None):
                # Log block reason for diagnosis
                feedback = getattr(response, "prompt_feedback", None)
                logger.error(
                    "Model returned no candidates. prompt_feedback=%s",
                    feedback,
                )
                msg = AIMessage(content="[Model returned no response. The request may have been blocked.]")
                return ChatResult(generations=[ChatGeneration(message=msg)])

            candidate = response.candidates[0]
            parts = getattr(getattr(candidate, "content", None), "parts", None) or []
            if not parts:
                msg = AIMessage(content="[Model returned empty content]")
                return ChatResult(generations=[ChatGeneration(message=msg)])

            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []

            for part in parts:
                if getattr(part, "text", None):
                    text_parts.append(part.text)

                fn_call = getattr(part, "function_call", None)
                if fn_call and getattr(fn_call, "name", None):
                    args: dict[str, Any] = {}
                    if getattr(fn_call, "args", None):
                        try:
                            args = dict(fn_call.args)
                        except Exception:
                            try:
                                args = json.loads(type(fn_call.args).to_json(fn_call.args))
                            except Exception:
                                args = {}
                    tool_calls.append(
                        {
                            "name": fn_call.name,
                            "args": args,
                            "id": str(uuid.uuid4()),
                            "type": "tool_call",
                        },
                    )

            message = AIMessage(content="\n".join(text_parts), tool_calls=tool_calls)
            return ChatResult(generations=[ChatGeneration(message=message)])

        except Exception as exc:
            if (not _auth_retry) and _is_auth_error(exc):
                logger.warning("Vertex auth error detected. Re-authenticating and retrying once.")
                self._initialize_vertex_model(force_auth=True)
                return self._generate(messages, stop, run_manager, _auth_retry=True, **kwargs)
            raise

    def bind_tools(
        self,
        tools: Union[Sequence[BaseTool], List[Any]],
        **kwargs: Any,
    ) -> "VertexAIChatModel":
        tool_list = list(tools)
        return self.__class__(
            model_name=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            system_instruction=self.system_instruction,
            tools=tool_list,
            vertex_tools=self._convert_tools_to_vertex_format(tool_list),
            response_schema=self.response_schema,
            response_mime_type=self.response_mime_type,
        )

    def with_structured_output(
        self,
        schema: Union[Dict[str, Any], type[BaseModel]],
        **kwargs: Any,
    ) -> "VertexAIChatModel":
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            raw_schema = schema.model_json_schema()
        elif isinstance(schema, dict):
            raw_schema = schema
        else:
            raise TypeError("schema must be a Pydantic model class or a JSON schema dict")

        return self.__class__(
            model_name=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            system_instruction=self.system_instruction,
            tools=self.tools,
            vertex_tools=self.vertex_tools,
            response_schema=_clean_schema(dict(raw_schema)),
            response_mime_type=kwargs.get("response_mime_type", "application/json"),
        )

    @property
    def _llm_type(self) -> str:
        return "vertexai_gemini_chat"


def VertexAILLM(
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    **kwargs: Any,
) -> BaseChatModel:
    """Factory function used by AgentFactory.

    Strictly returns the custom Vertex-based model. No fallback path is provided.
    """
    model_name = str(kwargs.pop("model_name", model))
    system_instruction = kwargs.pop("system_instruction", None)

    return VertexAIChatModel(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        system_instruction=system_instruction,
    )
