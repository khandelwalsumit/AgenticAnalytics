"""AgentFactory: create LangGraph agents from markdown skill definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from config.settings import AGENTS_DIR
from core.agent_loader import AgentSkill, load_agent, load_all_agents
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

    def make_agent(self, name: str, extra_context: str = "") -> Any:
        """Create a LangGraph ReAct agent from an agent definition."""
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

