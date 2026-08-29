from abc import ABC, abstractmethod
from typing import Any

from app.core.parser.schemas import SkillResult


class Skill(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, inputs: dict[str, Any]) -> SkillResult:
        """Execute the skill with normalized inputs."""

