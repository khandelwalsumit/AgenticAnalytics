"""AgentFactory: create LangGraph agents from markdown skill definitions.

Two agent creation paths:

1. **Structured output** — ``create_structured_chain()`` returns a reusable
   ``LLM.with_structured_output(Schema)`` chain.  Used by ``make_agent_node``
   at graph-build time so the binding is done once, not per invocation.

2. **ReAct (tool-using)** — ``make_agent()`` builds a LangGraph
   ``create_react_agent`` that can call tools.  Used for agents that need
   dynamic tool resolution.

Both paths read agent definitions from ``.md`` files via ``parse_agent_md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from agents.schemas import STRUCTURED_OUTPUT_SCHEMAS
from config import AGENTS_DIR
from core.agent_loader import AgentSkill, load_agent
from core.llm import get_llm


class AgentFactory:
    """Reads agent markdown files and instantiates LangGraph agents."""

    def __init__(
        self,
        definitions_dir: str | Path = AGENTS_DIR,
        llm_factory: Callable | None = None,
        tool_registry: dict[str, Callable] | None = None,
    ):
        self.definitions_dir = Path(definitions_dir)
        self.llm_factory = llm_factory or get_llm
        self.tool_registry = tool_registry or {}
        self._cache: dict[str, AgentSkill] = {}

    # -- Parsing -------------------------------------------------------------

    def parse_agent_md(self, name: str) -> AgentSkill:
        """Parse an agent markdown file into AgentSkill (cached)."""
        if name not in self._cache:
            path = self.definitions_dir / f"{name}.md"
            if not path.exists():
                raise FileNotFoundError(f"Agent definition not found: {path}")
            self._cache[name] = load_agent(path)
        return self._cache[name]

    # -- Internal helpers ----------------------------------------------------

    def _create_llm(self, name: str) -> Any:
        """Instantiate an LLM from the agent's .md config."""
        cfg = self.parse_agent_md(name)
        return self.llm_factory(
            model=cfg.model,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            max_tokens=cfg.max_tokens,
        )

    def _resolve_tools(self, tool_names: list[str]) -> list[Callable]:
        """Resolve tool names to callables from registry."""
        resolved: list[Callable] = []
        for name in tool_names:
            if name not in self.tool_registry:
                raise KeyError(
                    f"Tool '{name}' not found in registry. "
                    f"Available: {list(self.tool_registry.keys())}"
                )
            resolved.append(self.tool_registry[name])
        return resolved

    # -- Public API ----------------------------------------------------------

    def create_structured_chain(self, name: str) -> tuple[Any, type]:
        """Create a reusable ``with_structured_output`` chain for *name*.

        Returns ``(chain, schema)`` — store the chain and reuse it across
        invocations; wrap it in ``StructuredOutputAgent`` with a per-call
        system prompt to execute.

        Raises ``KeyError`` if *name* is not in ``STRUCTURED_OUTPUT_SCHEMAS``.
        """
        schema = STRUCTURED_OUTPUT_SCHEMAS.get(name)
        if schema is None:
            raise KeyError(
                f"Agent '{name}' has no structured-output schema. "
                f"Available: {list(STRUCTURED_OUTPUT_SCHEMAS.keys())}"
            )
        llm = self._create_llm(name)
        return llm.with_structured_output(schema), schema

    def make_agent(self, name: str, extra_context: str = "") -> Any:
        """Create a ReAct (tool-using) agent from an agent definition.

        For structured-output agents, use ``create_structured_chain`` instead
        — it is faster because the chain is built once and reused.
        """
        config = self.parse_agent_md(name)
        prompt = config.system_prompt
        if extra_context:
            prompt = f"{prompt}\n\n{extra_context}"

        llm = self._create_llm(name)
        tools = self._resolve_tools(config.tools)
        return create_react_agent(
            model=llm,
            tools=tools,
            prompt=SystemMessage(content=prompt),
        )


# ---------------------------------------------------------------------------
# StructuredOutputAgent
# ---------------------------------------------------------------------------


class StructuredOutputAgent:
    """Thin async wrapper around ``LLM.with_structured_output(Schema)``.

    Exposes ``ainvoke({"messages": [...]})`` so node code works identically
    for structured-output and ReAct agents.

    Result dict contains:
      ``structured_output`` — the validated Pydantic object
      ``messages``          — synthetic ``[AIMessage(json)]`` for message-chain compat
    """

    __slots__ = ("name", "system_prompt", "chain", "output_schema")

    def __init__(
        self,
        name: str,
        system_prompt: str,
        chain: Any,
        output_schema: type,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.chain = chain
        self.output_schema = output_schema

    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        """Invoke the structured-output chain."""
        messages = input.get("messages", [])
        full_messages = [SystemMessage(content=self.system_prompt)] + list(messages)
        result_obj = await self.chain.ainvoke(full_messages)
        return {
            "structured_output": result_obj,
            "messages": [AIMessage(content=result_obj.model_dump_json(indent=2))],
        }
