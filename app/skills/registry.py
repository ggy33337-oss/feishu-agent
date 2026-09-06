# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from app.skills.base import Skill


class SkillRegistry:
    default_config_path = Path(__file__).resolve().parents[2] / "config" / "skills.yaml"

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if not skill.name.strip():
            raise ValueError("Skill name cannot be empty.")
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' is already registered.")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._skills))
            raise ValueError(f"Skill '{name}' not found. Available: {available}") from exc

    def available_names(self) -> list[str]:
        return sorted(self._skills)

    def catalog(self) -> list[dict[str, str]]:
        return [
            {"name": name, "description": skill.description}
            for name, skill in sorted(self._skills.items())
        ]

    @classmethod
    def from_config(cls, path: Path) -> "SkillRegistry":
        with open(path, encoding="utf-8") as file_handle:
            payload = yaml.safe_load(file_handle) or {}
        entries = payload.get("skills") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("Skill config must contain a skills array.")

        registry = cls()
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue
            skill = cls._load_skill(entry)
            registry.register(skill)
        if not registry.available_names():
            raise ValueError("Skill config did not enable any skills.")
        return registry

    @staticmethod
    def _load_skill(entry: dict[str, Any]) -> Skill:
        module_name = str(entry.get("module") or "").strip()
        class_name = str(entry.get("class") or "").strip()
        if not module_name or not class_name:
            raise ValueError("Each skill requires module and class values.")
        module = importlib.import_module(module_name)
        skill_class = getattr(module, class_name, None)
        if not isinstance(skill_class, type) or not issubclass(skill_class, Skill):
            raise ValueError(f"Configured skill is not a Skill: {module_name}.{class_name}")
        return skill_class()

    @classmethod
    def default(cls) -> "SkillRegistry":
        return cls.from_config(cls.default_config_path)
