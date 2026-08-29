from app.core.parser.schemas import Plan, RouteDecision, StructuredTask


class Planner:
    """Create a simple execution plan from a parsed task."""

    def create_plan(self, task: StructuredTask, decision: RouteDecision) -> Plan:
        if decision.skill_name is None:
            raise ValueError("skill_name is required for tool plans")
        skill_name = decision.skill_name
        return Plan(
            task_id=task.task_id,
            skill_name=skill_name,
            steps=[
                "select_skill",
                f"execute_{skill_name}_skill",
                "format_response",
            ],
            inputs={
                "text": task.normalized_text,
                "attachments": task.attachments,
                "user_id": task.user_id,
                "chat_id": task.chat_id,
                "message_id": task.message_id,
                "task_type": task.task_type.value,
                "user_intent": task.user_intent,
                "entities": task.entities,
                "constraints": task.constraints,
                "decision_rationale": decision.rationale,
                "decision_confidence": decision.confidence,
                "parameters": decision.parameters,
            },
        )
