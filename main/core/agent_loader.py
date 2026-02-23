"""Agent loader aligned with Citi-Agentic style skill files.

Loads agent definitions from markdown files with optional YAML frontmatter.
This keeps agent definition parsing decoupled from AgentFactory so the same
agent files can be consumed by multiple orchestrators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


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
    """Return parsed frontmatter and markdown body."""
    if not text.startswith("---"):
        return {}, text.strip()

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text.strip()

    frontmatter_raw = parts[1].strip()
    body = parts[2].strip()
    frontmatter = yaml.safe_load(frontmatter_raw) if frontmatter_raw else {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, body


def load_agent(filepath: str | Path) -> AgentSkill:
    """Load a single agent definition from disk."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)

    return AgentSkill(
        name=frontmatter.get("name", path.stem),
        description=frontmatter.get("description", ""),
        system_prompt=body,
        model=frontmatter.get("model", "gemini-2.5-flash"),
        temperature=frontmatter.get("temperature", 0.1),
        top_p=frontmatter.get("top_p", 0.95),
        max_tokens=frontmatter.get("max_tokens", 8192),
        tools=frontmatter.get("tools", []),
        handoffs=frontmatter.get("handoffs", []),
        metadata=frontmatter.get("metadata", {}),
        source_file=str(path),
    )


def load_all_agents(agents_dir: str | Path) -> dict[str, AgentSkill]:
    """Load all markdown agent definitions from a directory."""
    root = Path(agents_dir)
    if not root.exists():
        raise FileNotFoundError(f"Agents directory not found: {root}")

    agents: dict[str, AgentSkill] = {}
    for path in sorted(root.glob("*.md")):
        skill = load_agent(path)
        agents[skill.name] = skill
    return agents

