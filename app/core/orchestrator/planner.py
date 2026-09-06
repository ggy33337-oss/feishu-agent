# -*- coding: utf-8 -*-
from app.domain.contracts import Plan, SkillContext, StructuredTask, WorkflowStep


class Planner:
    """Create a simple execution plan from a parsed task."""

    def create_plan(self, task: StructuredTask, step: WorkflowStep) -> Plan:
        return Plan(
            task_id=task.task_id,
            step_id=step.step_id,
            subtask_id=step.subtask_id,
            skill_name=step.skill_name,
            steps=[f"execute_{step.skill_name}_skill"],
            inputs=SkillContext.model_validate(
                {
                    "task_id": task.task_id,
                    "text": task.normalized_text,
                    "source_text": task.source_text,
                    "attachments": task.attachments,
                    "user_id": task.user_id,
                    "chat_id": task.chat_id,
                    "message_id": task.message_id,
                    "task_type": task.task_type.value,
                    "user_intent": task.user_intent,
                    "entities": task.entities,
                    "constraints": task.constraints,
                    "subtasks": [subtask.model_dump() for subtask in task.subtasks],
                    "step": step.model_dump(),
                    "parameters": step.parameters,
                    **step.inputs,
                }
            ),
        )
