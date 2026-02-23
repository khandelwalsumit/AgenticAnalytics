"""AgentFactory: create LangGraph agents from markdown skill definitions.

When an agent name is found in ``STRUCTURED_OUTPUT_SCHEMAS``, the factory
creates a *structured-output* pipeline:

    SystemMessage → LLM.with_structured_output(Schema) → Pydantic object

instead of the standard ``create_react_agent`` ReAct loop. This guarantees
schema-valid JSON responses and eliminates fragile regex/JSON post-parsing.

Agents that use tools still use ``create_react_agent`` as before; structured
output is only applied to planning / decision agents that don't need tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableSequence
from langgraph.prebuilt import create_react_agent

from agents.schemas import STRUCTURED_OUTPUT_SCHEMAS
from config import AGENTS_DIR
from core.agent_loader import AgentSkill, load_agent, load_all_agents
from core.llm import get_llm


class AgentFactory:
    """Reads agent markdown files and instantiates LangGraph agents.

    For agents listed in ``STRUCTURED_OUTPUT_SCHEMAS``, ``make_agent`` returns
    a ``StructuredOutputAgent`` wrapper instead of a ReAct agent.  The wrapper
    exposes the same ``ainvoke({"messages": [...]})`` interface so node code
    stays uniform.
    """

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

    def _agent_path(self, name: str) -> Path:
        return self.definitions_dir / f"{name}.md"

    def parse_agent_md(self, name: str) -> AgentSkill:
        """Parse an agent markdown file into AgentSkill."""
        if name in self._cache:
            return self._cache[name]

        path = self._agent_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Agent definition not found: {path}")

        config = load_agent(path)
        self._cache[name] = config
        return config

    def load_agent(self, name: str) -> AgentSkill:
        """Compatibility helper aligned with Citi-Agentic loader API."""
        return self.parse_agent_md(name)

    def load_all_agents(self) -> dict[str, AgentSkill]:
        """Load all agent definitions from this factory's directory."""
        return load_all_agents(self.definitions_dir)

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

    def create_structured_chain(self, name: str) -> tuple[Any, type]:
        """Create a reusable ``with_structured_output`` chain for *name*.

        Returns:
            (chain, schema) — the bound LLM chain and the Pydantic schema
            class.  The chain can be stored and reused across invocations;
            wrap it in a ``StructuredOutputAgent`` with a per-call system
            prompt to execute.

        Raises:
            KeyError: if *name* is not in ``STRUCTURED_OUTPUT_SCHEMAS``.
        """
        schema = STRUCTURED_OUTPUT_SCHEMAS.get(name)
        if schema is None:
            raise KeyError(
                f"Agent '{name}' has no structured-output schema. "
                f"Available: {list(STRUCTURED_OUTPUT_SCHEMAS.keys())}"
            )
        config = self.parse_agent_md(name)
        llm = self.llm_factory(
            model=config.model,
            temperature=config.temperature,
            top_p=config.top_p,
            max_tokens=config.max_tokens,
        )
        return llm.with_structured_output(schema), schema

    def make_agent(self, name: str, extra_context: str = "") -> Any:
        """Create an agent from an agent definition.

        If the agent is in STRUCTURED_OUTPUT_SCHEMAS, returns a
        ``StructuredOutputAgent`` (LLM bound with ``with_structured_output``).
        Otherwise, returns a standard LangGraph ReAct agent.

        .. note::

            For performance-critical paths, prefer calling
            ``create_structured_chain`` once at graph-build time and
            reusing the chain across invocations (see ``make_agent_node``
            in ``agents.nodes``).
        """
        config = self.parse_agent_md(name)

        prompt = config.system_prompt
        if extra_context:
            prompt = f"{prompt}\n\n{extra_context}"

        llm = self.llm_factory(
            model=config.model,
            temperature=config.temperature,
            top_p=config.top_p,
            max_tokens=config.max_tokens,
        )

        # -- Structured output path -------------------------------------------
        schema = STRUCTURED_OUTPUT_SCHEMAS.get(name)
        if schema is not None:
            structured_llm = llm.with_structured_output(schema)
            return StructuredOutputAgent(
                name=name,
                system_prompt=prompt,
                chain=structured_llm,
                output_schema=schema,
            )

        # -- Standard ReAct path (tool-using agents) --------------------------
        tools = self._resolve_tools(config.tools)
        return create_react_agent(
            model=llm,
            tools=tools,
            prompt=SystemMessage(content=prompt),
        )

    def make_node(self, name: str, extra_context: str = "") -> Callable:
        """Build a node function that invokes the configured agent."""
        agent = self.make_agent(name, extra_context=extra_context)

        async def node_fn(state: dict) -> dict:
            result = await agent.ainvoke({"messages": state["messages"]})
            return {"messages": result["messages"]}

        node_fn.__name__ = f"{name}_node"
        return node_fn


# ---------------------------------------------------------------------------
# StructuredOutputAgent
# ---------------------------------------------------------------------------


class StructuredOutputAgent:
    """Thin async wrapper around an LLM chain built with ``with_structured_output``.

    Exposes the same ``ainvoke({"messages": [...]})`` interface as a LangGraph
    ReAct agent so that node code in ``nodes.py`` works identically for both
    structured-output and tool-using agents.

    The result dict always contains:
      ``structured_output`` — the validated Pydantic object (the primary payload)
      ``messages``          — a synthetic list with one AIMessage whose content
                             is the JSON-serialised structured output, so that
                             existing message-inspection code still works.
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        chain: Any,
        output_schema: type,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.chain = chain  # LLM.with_structured_output(Schema)
        self.output_schema = output_schema

    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        """Invoke the structured-output chain.

        Prepends the system prompt as the first message, then passes the full
        conversation to the bound LLM chain.
        """
        from langchain_core.messages import AIMessage, SystemMessage

        messages = input.get("messages", [])
        # Build message list: system prompt + conversation
        full_messages = [SystemMessage(content=self.system_prompt)] + list(messages)

        # Invoke the structured chain — returns a Pydantic object
        result_obj = await self.chain.ainvoke(full_messages)

        # Serialise to JSON for the synthetic AIMessage
        result_json = result_obj.model_dump_json(indent=2)
        synthetic_ai_msg = AIMessage(content=result_json)

        return {
            "structured_output": result_obj,
            "messages": [synthetic_ai_msg],
        }
