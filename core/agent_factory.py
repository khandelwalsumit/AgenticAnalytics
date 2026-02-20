"""AgentFactory: reads agent .md files and creates LangGraph agents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from config.settings import AGENTS_DIR
from core.llm import get_llm


@dataclass
class AgentConfig:
    """Parsed configuration from an agent markdown file."""

    name: str = ""
    model: str = "gemini-pro"
    temperature: float = 0.1
    top_p: float = 0.95
    max_tokens: int = 8192
    description: str = ""
    tools: list[str] = field(default_factory=list)
    system_prompt: str = ""


class AgentFactory:
    """Reads agent .md files → creates LangGraph agents with VertexAI."""

    def __init__(
        self,
        definitions_dir: str | Path = AGENTS_DIR,
        llm_factory: Callable | None = None,
        tool_registry: dict[str, Callable] | None = None,
    ):
        self.definitions_dir = Path(definitions_dir)
        self.llm_factory = llm_factory or get_llm
        self.tool_registry = tool_registry or {}
        self._cache: dict[str, AgentConfig] = {}

    def parse_agent_md(self, name: str) -> AgentConfig:
        """Parse YAML frontmatter + system prompt from .md file."""
        if name in self._cache:
            return self._cache[name]

        md_path = self.definitions_dir / f"{name}.md"
        if not md_path.exists():
            raise FileNotFoundError(f"Agent definition not found: {md_path}")

        raw = md_path.read_text(encoding="utf-8")

        # Split frontmatter from body
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
        if not match:
            raise ValueError(f"Agent {name}: missing YAML frontmatter (---)")

        frontmatter = yaml.safe_load(match.group(1))
        body = match.group(2).strip()

        config = AgentConfig(
            name=frontmatter.get("name", name),
            model=frontmatter.get("model", "gemini-pro"),
            temperature=frontmatter.get("temperature", 0.1),
            top_p=frontmatter.get("top_p", 0.95),
            max_tokens=frontmatter.get("max_tokens", 8192),
            description=frontmatter.get("description", ""),
            tools=frontmatter.get("tools", []),
            system_prompt=body,
        )
        self._cache[name] = config
        return config

    def _resolve_tools(self, tool_names: list[str]) -> list[Callable]:
        """Resolve tool names to callable functions from registry."""
        resolved = []
        for name in tool_names:
            if name not in self.tool_registry:
                raise KeyError(
                    f"Tool '{name}' not found in registry. "
                    f"Available: {list(self.tool_registry.keys())}"
                )
            resolved.append(self.tool_registry[name])
        return resolved

    def make_agent(self, name: str, extra_context: str = "") -> Any:
        """Create a LangGraph agent using create_react_agent.

        - Reads agent .md → parses config + prompt
        - Resolves tools from registry
        - Optionally appends XML-wrapped skill content (extra_context)
        - Creates ChatVertexAI with config params
        - Returns compiled agent via create_react_agent
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

        tools = self._resolve_tools(config.tools)

        agent = create_react_agent(
            model=llm,
            tools=tools,
            prompt=SystemMessage(content=prompt),
        )
        return agent

    def make_node(self, name: str, extra_context: str = "") -> Callable:
        """Returns a node function for use in the main StateGraph.

        The node function accepts the full AnalyticsState and runs the agent,
        returning updated state fields.
        """
        agent = self.make_agent(name, extra_context=extra_context)

        async def node_fn(state: dict) -> dict:
            result = await agent.ainvoke({"messages": state["messages"]})
            return {"messages": result["messages"]}

        node_fn.__name__ = f"{name}_node"
        return node_fn
