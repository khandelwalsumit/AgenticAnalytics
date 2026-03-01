"""AgentFactory: parse agent .md definitions and create LangGraph agents.

Two agent creation paths:

1. **Structured output** — ``create_structured_chain()`` returns a reusable
   ``LLM.with_structured_output(Schema)`` chain.

2. **ReAct (tool-using)** — ``make_agent()`` builds a LangGraph
   ``create_react_agent`` that can call tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml
from langchain_core.messages import AIMessage, SystemMessage
from langchain.agents import create_agent

from agents.schemas import STRUCTURED_OUTPUT_SCHEMAS
from config import AGENTS_DIR
from core.llm import VertexAILLM


# ------------------------------------------------------------------
# Agent definition dataclass + parser
# ------------------------------------------------------------------


@dataclass
class AgentSkill:
    """Parsed agent definition from a markdown skill file."""

    name: str
    description: str
    system_prompt: str
    model: str = "gemini-2.5-flash"
    temperature: float = 0.1
    top_p: float = 0.95
    max_tokens: int = 8192
    tools: list[str] = field(default_factory=list)
    handoffs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return parsed YAML frontmatter and markdown body."""
    if not text.startswith("---"):
        return {}, text.strip()

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text.strip()

    raw = parts[1].strip()
    body = parts[2].strip()
    frontmatter = yaml.safe_load(raw) if raw else {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, body


def load_agent(filepath: str | Path) -> AgentSkill:
    """Load a single agent definition from disk."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)

    return AgentSkill(
        name=fm.get("name", path.stem),
        description=fm.get("description", ""),
        system_prompt=body,
        model=fm.get("model", "gemini-2.5-flash"),
        temperature=fm.get("temperature", 0.1),
        top_p=fm.get("top_p", 0.95),
        max_tokens=fm.get("max_tokens", 8192),
        tools=fm.get("tools") or [],
        handoffs=fm.get("handoffs") or [],
        metadata=fm.get("metadata", {}),
        source_file=str(path),
    )


def load_all_agents(agents_dir: str | Path) -> dict[str, AgentSkill]:
    """Load all markdown agent definitions from a directory."""
    root = Path(agents_dir)
    return {skill.name: skill for path in sorted(root.glob("*.md")) for skill in [load_agent(path)]}


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------


class AgentFactory:
    """Reads agent .md files and creates LangGraph agents."""

    def __init__(
        self,
        definitions_dir: str | Path = AGENTS_DIR,
        llm_factory: Callable | None = None,
        tool_registry: dict[str, Callable] | None = None,
    ):
        self.definitions_dir = Path(definitions_dir)
        self.llm_factory = llm_factory or VertexAILLM
        self.tool_registry = tool_registry or {}
        self._cache: dict[str, AgentSkill] = {}

    def parse_agent_md(self, name: str) -> AgentSkill:
        """Parse an agent markdown file into AgentSkill (cached)."""
        if name not in self._cache:
            path = self.definitions_dir / f"{name}.md"
            self._cache[name] = load_agent(path)
        return self._cache[name]

    def _create_llm(self, name: str) -> Any:
        cfg = self.parse_agent_md(name)
        return self.llm_factory(
            model=cfg.model,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            max_tokens=cfg.max_tokens,
        )

    def _resolve_tools(self, tool_names: list[str]) -> list[Callable]:
        return [self.tool_registry[n] for n in tool_names]

    def create_structured_chain(self, name: str) -> tuple[Any, type]:
        """Create a reusable ``with_structured_output`` chain."""
        schema = STRUCTURED_OUTPUT_SCHEMAS[name]
        llm = self._create_llm(name)
        return llm.with_structured_output(schema), schema

    def make_agent(self, name: str, extra_context: str = "") -> Any:
        """Create a ReAct (tool-using) agent."""
        config = self.parse_agent_md(name)
        prompt = config.system_prompt
        if extra_context:
            prompt = f"{prompt}\n\n{extra_context}"

        llm = self._create_llm(name)
        tools = self._resolve_tools(config.tools)

        return create_agent(
            model=llm,
            tools=tools,
            system_prompt=SystemMessage(content=prompt),
        )


# ------------------------------------------------------------------
# StructuredOutputAgent — thin wrapper so node code is identical
# for structured-output and ReAct agents
# ------------------------------------------------------------------


class StructuredOutputAgent:
    """Wraps ``LLM.with_structured_output(Schema)`` with async ainvoke."""

    __slots__ = ("name", "system_prompt", "chain", "output_schema")

    def __init__(self, name: str, system_prompt: str, chain: Any, output_schema: type) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.chain = chain
        self.output_schema = output_schema

    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        messages = input.get("messages", [])
        full_messages = [SystemMessage(content=self.system_prompt)] + list(messages)
        result_obj = await self.chain.ainvoke(full_messages)
        # Wrapper returns AIMessage(content=JSON) instead of Pydantic instance — parse it.
        if not isinstance(result_obj, self.output_schema):
            result_obj = self.output_schema(**json.loads(result_obj.content))
        return {
            "structured_output": result_obj,
            "messages": [AIMessage(content=result_obj.model_dump_json(indent=2))],
        }
