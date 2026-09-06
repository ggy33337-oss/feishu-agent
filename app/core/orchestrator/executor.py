# -*- coding: utf-8 -*-
from app.domain.contracts import Plan, SkillResult
from app.skills.registry import SkillRegistry
from app.core.orchestrator.stages import PipelineStage
from app.services.timing import timed_stage

import logging


logger = logging.getLogger(__name__)


class Executor:
    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or SkillRegistry.default()

    async def execute(self, plan: Plan) -> SkillResult:
        skill = self.registry.get(plan.skill_name)
        async with timed_stage(
            logger,
            f"{PipelineStage.TOOL}.{plan.skill_name}",
            job_id=str(plan.inputs.get("job_id") or "") or None,
            fields={
                "task_id": plan.task_id,
                "step_id": plan.step_id,
                "skill_name": plan.skill_name,
            },
        ):
            return await skill.run(plan.inputs)
