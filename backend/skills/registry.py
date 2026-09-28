"""
backend/skills/registry.py — skill framework + dynamic selection (Phase 4).
═══════════════════════════════════════════════════════════════════════════════
A skill lives in skills/<name>/ as:
  • skill.json  — name, description, triggers, instructions, allowed_tools, permissions, io_schema
  • handler.py  — exposes `async def handle(ctx, query) -> dict` returning {"reply", ...}

The registry loads every skill at startup, and select() picks the best skill for a
query by scoring trigger-keyword matches (deterministic + testable). The agent runs
the selected skill's handler; if none matches, it falls back to normal chat.

SkillContext gives handlers the services they're allowed to use. Permissions are
declared here and enforced fully in Phase 5's tool layer; trading stays read-only.
"""
from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..logging_setup import get_logger

log = get_logger("jarvis.skills")
# jarvis/backend/skills/registry.py → parents[2] = project root (avoid importing config
# so the registry stays lightweight and testable without pydantic).
ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "skills"


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str]
    instructions: str
    allowed_tools: list[str]
    permissions: dict
    io_schema: dict
    handler: Callable            # async def handle(ctx, query) -> dict
    dir: Path

    def score(self, query: str) -> int:
        """Count distinct trigger phrases present in the query (word-boundary, case-insensitive)."""
        q = query.lower()
        hits = 0
        for t in self.triggers:
            t = t.lower().strip()
            if not t:
                continue
            if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", q):
                hits += 1
        return hits


@dataclass
class SkillContext:
    """What a handler may use. Populated by the agent per turn."""
    settings: Any = None
    db: Any = None
    memory: Any = None
    router: Any = None
    channel: str = "web"
    extras: dict = field(default_factory=dict)


class SkillRegistry:
    def __init__(self, skills: list[Skill]):
        self.skills = skills
        self.by_name = {s.name: s for s in skills}

    @classmethod
    def load(cls, skills_dir: Path = SKILLS_DIR) -> "SkillRegistry":
        skills: list[Skill] = []
        if not skills_dir.exists():
            log.warning("skills.dir_missing", extra={"dir": str(skills_dir)})
            return cls([])
        for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            manifest = d / "skill.json"
            handler_py = d / "handler.py"
            if not manifest.exists() or not handler_py.exists():
                continue
            try:
                spec = json.loads(manifest.read_text(encoding="utf-8"))
                handler = _load_handler(handler_py, d.name)
                skills.append(Skill(
                    name=spec["name"],
                    description=spec.get("description", ""),
                    triggers=spec.get("triggers", []),
                    instructions=spec.get("instructions", ""),
                    allowed_tools=spec.get("allowed_tools", []),
                    permissions=spec.get("permissions", {}),
                    io_schema=spec.get("io_schema", {}),
                    handler=handler, dir=d,
                ))
                log.info("skills.loaded", extra={"skill": spec["name"]})
            except Exception as e:
                log.warning("skills.load_failed", extra={"dir": d.name, "error": str(e)})
        return cls(skills)

    def select(self, query: str, min_score: int = 1) -> Skill | None:
        best, best_score = None, 0
        for s in self.skills:
            sc = s.score(query)
            if sc > best_score:
                best, best_score = s, sc
        return best if best_score >= min_score else None

    def list_skills(self) -> list[dict]:
        return [{"name": s.name, "description": s.description, "triggers": s.triggers,
                 "permissions": s.permissions} for s in self.skills]


def _load_handler(handler_py: Path, mod_name: str) -> Callable:
    spec = importlib.util.spec_from_file_location(f"jarvis_skill_{mod_name}", handler_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    if not hasattr(module, "handle"):
        raise AttributeError(f"{handler_py} has no handle()")
    return module.handle
