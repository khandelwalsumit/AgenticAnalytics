"""SkillLoader: reads skill .md files, wraps in XML tags, injects into prompts."""

from __future__ import annotations

from pathlib import Path

from config.settings import SKILLS_DIR


class SkillLoader:
    """Reads skill .md files, wraps in XML tags, and provides them for prompt injection."""

    CATEGORIES = ("domain", "operational")

    def __init__(self, skills_dir: str | Path = SKILLS_DIR):
        self.skills_dir = Path(skills_dir)

    def _resolve_skill(self, name: str) -> tuple[str, Path]:
        """Find skill file across categories. Returns (category, path)."""
        for category in self.CATEGORIES:
            path = self.skills_dir / category / f"{name}.md"
            if path.exists():
                return category, path
        raise FileNotFoundError(
            f"Skill '{name}' not found in any category under {self.skills_dir}"
        )

    def load_skill(self, name: str) -> str:
        """Load a skill markdown file and wrap in XML tags.

        Returns:
            <skill name="payment_transfer" category="domain">
            ...content...
            </skill>
        """
        category, path = self._resolve_skill(name)
        content = path.read_text(encoding="utf-8").strip()
        return f'<skill name="{name}" category="{category}">\n{content}\n</skill>'

    def load_skills(self, skill_names: list[str]) -> str:
        """Load multiple skills, each XML-wrapped, concatenated."""
        parts = []
        for name in skill_names:
            parts.append(self.load_skill(name))
        return "\n\n".join(parts)

    def list_skills(self) -> dict[str, list[str]]:
        """Returns available skills grouped by category."""
        result: dict[str, list[str]] = {}
        for category in self.CATEGORIES:
            category_dir = self.skills_dir / category
            if category_dir.exists():
                result[category] = sorted(
                    p.stem for p in category_dir.glob("*.md")
                )
        return result
