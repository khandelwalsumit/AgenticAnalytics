from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain.tools import BaseTool
from typing import Any, Optional, List, Dict, Sequence, Union, Tuple
from pydantic import Field, BaseModel
import json
import logging
import uuid

from config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    BACKOFF_MAX_DELAY,
)

import time
import random
from google.api_core.exceptions import TooManyRequests, ResourceExhausted
from vertexai.generative_models import (
    GenerativeModel, 
    GenerationConfig, 
    Tool as VertexTool, 
    FunctionDeclaration,
    Content,
    Part
)

from core.auth import authenticate_vertexai

logger = logging.getLogger(__name__)


def _clean_schema(schema: dict) -> dict:
    """Remove keys that Vertex AI's FunctionDeclaration doesn't accept, including $ref everywhere."""
    blocked_keys = {"additionalProperties", "title", "$defs", "definitions", "$ref"}
    cleaned = {k: v for k, v in schema.items() if k not in blocked_keys}
    # Recursively clean nested properties
    if "properties" in cleaned:
        cleaned["properties"] = {
            k: _clean_schema(v) if isinstance(v, dict) else v
            for k, v in cleaned["properties"].items()
        }
    if "items" in cleaned and isinstance(cleaned["items"], dict):
        cleaned["items"] = _clean_schema(cleaned["items"])
    return cleaned


class VertexAILLM(BaseChatModel):
    """Custom Chat Model wrapper for Vertex AI Gemini models with tool calling and response schema support.
    
    This implementation is designed for LangGraph and follows standard LangChain patterns:
    - Tool calls are exposed via AIMessage.tool_calls (not executed internally)
    - ToolMessage inputs are properly handled
    - System instructions are set via model initialization
    """
    
    model_name: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    top_p: float = DEFAULT_TOP_P
    
    # System instruction support (set once during initialization)
    system_instruction: Optional[str] = None
    
    # Response schema support
    response_schema: Optional[Dict[str, Any]] = None
    response_mime_type: Optional[str] = None
    
    # Use Field for mutable defaults
    tools: List[BaseTool] = Field(default_factory=list)
    vertex_tools: List[VertexTool] = Field(default_factory=list)
    
    # Non-pydantic fields
    gen_model: Optional[Any] = None
    generation_config: Optional[Any] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        self._initialize_vertex_ai()

    def _initialize_vertex_ai(self):
        """Initialize Vertex AI with proper authentication."""
        try:
            authenticate_vertexai()
            # Build generation config with optional response schema
            gen_config_params = {
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
                "top_p": self.top_p,
            }
            
            # Add response schema if provided
            if self.response_schema:
                gen_config_params["response_schema"] = self.response_schema
                gen_config_params["response_mime_type"] = self.response_mime_type or "application/json"
            
            self.generation_config = GenerationConfig(**gen_config_params)
            
            # Initialize model with optional system instruction
            self.gen_model = GenerativeModel(
                self.model_name,
                system_instruction=self.system_instruction
            )
        except Exception as e:
            raise Exception(f"Error initializing Vertex AI: {str(e)}")

    def _langchain_tool_to_vertex_fd(self, tool: BaseTool) -> FunctionDeclaration:
        """Convert a LangChain tool to a Vertex FunctionDeclaration."""
        # Extract schema from tool
        if hasattr(tool, 'args_schema') and tool.args_schema:
            schema = tool.args_schema.model_json_schema()
            params = _clean_schema(schema)
        else:
            # Fallback if no schema
            params = {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input to the tool"}
                },
                "required": ["input"]
            }
        
        return FunctionDeclaration(
            name=tool.name,
            description=tool.description or "Tool function",
            parameters=params if params and params.get("properties") else {},
        )

    def _convert_tools_to_vertex_format(self, tools: List[BaseTool]) -> List[VertexTool]:
        """Convert LangChain tools to Vertex AI tool format."""
        function_declarations = []
        
        for tool in tools:
            function_declarations.append(self._langchain_tool_to_vertex_fd(tool))
        
        # Wrap all function declarations in a single VertexTool
        return [VertexTool(function_declarations=function_declarations)]

    def _convert_messages_to_vertex_format(self, messages: List[BaseMessage]) -> tuple[List[Content], Optional[str]]:
        """Convert LangChain messages to Vertex AI Content format.
        
        Handles:
        - HumanMessage → user content
        - AIMessage (with optional tool_calls) → model content
        - ToolMessage → tool content with function responses
        - SystemMessage → extracted and returned as system instruction
        
        Returns:
            Tuple of (contents, extracted_system_instruction)
        """
        contents = []
        extracted_system_instruction = None
        
        for message in messages:
            if isinstance(message, HumanMessage):
                contents.append(Content(role="user", parts=[Part.from_text(message.content)]))
            
            elif isinstance(message, AIMessage):
                ai_parts = []
                
                # Add text content if present
                if message.content:
                    ai_parts.append(Part.from_text(message.content))
                
                # Add tool calls if present (from LangGraph)
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    for tool_call in message.tool_calls:
                        ai_parts.append(
                            Part.from_dict({
                                "function_call": {
                                    "name": tool_call.get("name") if isinstance(tool_call, dict) else tool_call.name,
                                    "args": tool_call.get("args", {}) if isinstance(tool_call, dict) else tool_call.args
                                }
                            })
                        )
                
                if ai_parts:
                    contents.append(Content(role="model", parts=ai_parts))
            
            elif isinstance(message, ToolMessage):
                # Handle tool results from LangGraph
                # ToolMessage.content should contain the raw result from tool execution
                
                # Convert the content to a proper dictionary format for Vertex AI
                # Vertex AI expects function response to be a dict-like structure
                if isinstance(message.content, str):
                    try:
                        # Try parsing as JSON first
                        parsed_content = json.loads(message.content)
                        if isinstance(parsed_content, dict):
                            tool_output = parsed_content
                        else:
                            tool_output = {"result": parsed_content}
                    except json.JSONDecodeError:
                        tool_output = {"result": message.content}
                elif isinstance(message.content, dict):
                    tool_output = message.content
                else:
                    # For any other type (int, float, list, etc.), wrap in result key
                    tool_output = {"result": message.content}
                
                contents.append(
                    Content(role="tool", parts=[
                        Part.from_function_response(
                            name=message.name,
                            response=tool_output
                        )
                    ])
                )
            
            elif isinstance(message, SystemMessage):
                # Extract system instruction from SystemMessage
                # This allows compatibility with create_agent which uses SystemMessage
                if not extracted_system_instruction:
                    extracted_system_instruction = message.content
                else:
                    # If multiple system messages, concatenate them
                    extracted_system_instruction += "\n" + message.content
                continue
        
        return contents, extracted_system_instruction

    def _exponential_backoff_retry(self, func, *args, **kwargs):
        """Execute function with exponential backoff retry logic."""
        delay = 1
        
        for attempt in range(10):
            try:
                return func(*args, **kwargs)
            except (TooManyRequests, ResourceExhausted) as e:
                if attempt == 9:  # Last attempt (0-indexed)
                    logger.error(f"Max retries (10) exceeded. Final error: {str(e)}")
                    raise Exception(f"Rate limit exceeded after 10 retries: {str(e)}")
                
                # Calculate delay with jitter
                actual_delay = delay * (0.7 + random.random() * 0.3)
                
                logger.warning(
                    f" [BACKOFF] Rate limit hit (attempt {attempt + 1}/10). "
                    f"Retrying in {actual_delay:.1f}s..."
                )
                
                time.sleep(actual_delay)
                
                # Exponential backoff with cap
                delay = min(2**attempt, BACKOFF_MAX_DELAY)
            except Exception as e:
                # For non-rate-limit errors, don't retry
                logger.error(f"Non-retryable error: {str(e)}")
                raise

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        _r2d2_retry: bool = False,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate a response from messages.
        
        This implementation follows LangGraph patterns:
        - Returns AIMessage with tool_calls when model suggests tools
        - Does NOT execute tools internally (LangGraph handles that)
        - Properly handles ToolMessage inputs from LangGraph
        """
        try:
            authenticate_vertexai()
            # Convert LangChain messages to Vertex AI format
            contents, extracted_system_instruction = self._convert_messages_to_vertex_format(messages)
            
            # Determine which system instruction to use
            # Priority: extracted from messages > initialization parameter
            active_system_instruction = extracted_system_instruction or self.system_instruction
            
            # Build generation config with optional response schema
            gen_config_params = {
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
                "top_p": self.top_p,
            }
            
            if stop:
                gen_config_params["stop_sequences"] = stop
            
            # Add response schema if provided (can be overridden in kwargs)
            if "response_schema" in kwargs:
                gen_config_params["response_schema"] = kwargs["response_schema"]
                gen_config_params["response_mime_type"] = kwargs.get("response_mime_type", "application/json")
            elif self.response_schema:
                gen_config_params["response_schema"] = self.response_schema
                gen_config_params["response_mime_type"] = self.response_mime_type or "application/json"
            
            gen_config = GenerationConfig(**gen_config_params)
            
            # Build generate_content kwargs
            call_kwargs = {
                "generation_config": gen_config,
            }
            
            # Only pass tools if we have them
            if self.vertex_tools:
                call_kwargs["tools"] = self.vertex_tools
            
            # If we have a dynamic system instruction, create a temporary model
            if active_system_instruction and active_system_instruction != self.system_instruction:
                temp_model = GenerativeModel(
                    self.model_name,
                    system_instruction=active_system_instruction
                )
                
                # Call the temporary model
                if BACKOFF_MAX_DELAY:
                    response = self._exponential_backoff_retry(
                        temp_model.generate_content, 
                        contents, 
                        **call_kwargs
                    )
                else:
                    response = temp_model.generate_content(contents, **call_kwargs)
            else:
                # Call the model (single turn - LangGraph handles multi-turn)
                if BACKOFF_MAX_DELAY:
                    response = self._exponential_backoff_retry(
                        self.gen_model.generate_content, 
                        contents, 
                        **call_kwargs
                    )
                else:
                    response = self.gen_model.generate_content(contents, **call_kwargs)
            
            # Handle empty response
            if not response.candidates:
                logger.warning("Vertex AI returned no candidates.")
                message = AIMessage(content="[Model returned no response. The request may have been blocked.]")
                return ChatResult(generations=[ChatGeneration(message=message)])
            
            candidate = response.candidates[0]
            
            # Check if response was blocked
            if hasattr(candidate, 'finish_reason'):
                finish_reason = str(candidate.finish_reason)
                if finish_reason not in ("1", "STOP", "FinishReason.STOP"):
                    logger.info(f" [STOP] Vertex AI finish_reason: {finish_reason}")
            
            # Handle candidate with no content
            if not hasattr(candidate, "content") or not candidate.content:
                message = AIMessage(content="[Model returned empty content]")
                return ChatResult(generations=[ChatGeneration(message=message)])
            
            if not candidate.content.parts:
                message = AIMessage(content="[Model returned no content parts]")
                return ChatResult(generations=[ChatGeneration(message=message)])
            
            # Parse the response parts
            text_parts = []
            tool_calls_list = []
            
            for part in candidate.content.parts:
                # Check for text
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
                
                # Check for function call
                fn_call = getattr(part, "function_call", None)
                if fn_call and getattr(fn_call, "name", None):
                    args = {}
                    if fn_call.args:
                        try:
                            args = dict(fn_call.args)
                        except Exception:
                            args = json.loads(type(fn_call.args).to_json(fn_call.args))
                    
                    # Create ToolCall object for LangGraph
                    tool_calls_list.append(
                        ToolCall(
                            name=fn_call.name,
                            args=args,
                            id=str(uuid.uuid4())
                        )
                    )
            
            # Build the AIMessage
            content = "\n".join(text_parts) if text_parts else ""
            
            # Create AIMessage with tool_calls if present
            message = AIMessage(
                content=content,
                tool_calls=tool_calls_list if tool_calls_list else []
            )
            
            # Log what we're returning
            # if tool_calls_list:
            #     logger.info(f" [AI] Returning {len(tool_calls_list)} tool call(s): {[tc.name for tc in tool_calls_list]}")
            # else:
            #     logger.info(f" [AI] Returning text response: {content[:200]}")
            
            return ChatResult(generations=[ChatGeneration(message=message)])
            
        except Exception as e:
            error_str = str(e).lower()
            is_auth_error = any(code in error_str for code in ["400", "401", "403", "unauthenticated", "invalid credentials"])
            
            if _r2d2_retry and is_auth_error:
                logger.warning("[AUTH] Got auth error, forcing token refresh and retrying...")
                authenticate_vertexai(force=True)
                return self._generate(messages,stop, run_manager, _r2d2_retry=True, **kwargs)   # one retry after fresh token
            raise

    def bind_tools(
        self,
        tools: Union[Sequence[BaseTool], List[Any]],
        **kwargs: Any,
    ) -> "VertexAILLM":
        """Bind tools to the model for tool calling.
        
        Creates a new instance with tools bound.
        """
        # Convert tools to Vertex format
        vertex_tools = self._convert_tools_to_vertex_format(list(tools))
        
        # Create a new instance with the same config but with tools
        return self.__class__(
            model_name=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            system_instruction=self.system_instruction,
            tools=list(tools),
            vertex_tools=vertex_tools,
            response_schema=self.response_schema,
            response_mime_type=self.response_mime_type,
        )

    def with_structured_output(
        self,
        schema: Union[Dict[str, Any], type[BaseModel]],
        **kwargs: Any
    ) -> "VertexAILLM":
        """Bind a response schema for structured output.
        
        Args:
            schema: Either a Pydantic model or a JSON schema dict
            **kwargs: Additional arguments (e.g., response_mime_type)
        
        Returns:
            A new instance with response schema bound
        """
        # Convert Pydantic model to JSON schema if needed
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            json_schema = schema.model_json_schema()
            # Clean the schema for Vertex AI
            json_schema = _clean_schema(json_schema)
        else:
            json_schema = _clean_schema(schema)
        
        # Create a new instance with response schema
        return self.__class__(
            model_name=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            system_instruction=self.system_instruction,
            tools=self.tools,
            vertex_tools=self.vertex_tools,
            response_schema=json_schema,
            response_mime_type=kwargs.get("response_mime_type", "application/json"),
        )

    @property
    def _llm_type(self) -> str:
        """Return type of llm."""
        return "vertexai_gemini_chat"