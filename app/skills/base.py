# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod

from app.domain.contracts import SkillContext, SkillResult


class Skill(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, inputs: SkillContext | dict[str, object]) -> SkillResult:
        """Execute the skill with normalized inputs."""

    @staticmethod
    def context(inputs: SkillContext | dict[str, object]) -> SkillContext:
        if isinstance(inputs, SkillContext):
            return inputs
        return SkillContext.model_validate(inputs)
