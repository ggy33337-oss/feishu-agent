# -*- coding: utf-8 -*-
from __future__ import annotations

from app.domain.contracts import WorkflowStep


def topological_batches(steps: list[WorkflowStep]) -> list[list[WorkflowStep]]:
    """Return deterministic parallel batches for a validated dependency graph."""
    ordered = sorted(steps, key=lambda item: (item.order, item.step_id))
    by_id = {step.step_id: step for step in ordered}
    if len(by_id) != len(ordered):
        raise ValueError("Workflow step_id values must be unique.")

    subtask_to_step: dict[str, str] = {}
    for step in ordered:
        subtask_to_step.setdefault(step.subtask_id, step.step_id)

    dependencies: dict[str, set[str]] = {}
    for step in ordered:
        resolved: set[str] = set()
        for dependency in step.depends_on:
            dependency_id = dependency if dependency in by_id else subtask_to_step.get(dependency)
            if not dependency_id:
                raise ValueError(
                    f"Workflow step '{step.step_id}' depends on unknown step '{dependency}'."
                )
            if dependency_id == step.step_id:
                raise ValueError(f"Workflow step '{step.step_id}' cannot depend on itself.")
            resolved.add(dependency_id)
        dependencies[step.step_id] = resolved

    batches: list[list[WorkflowStep]] = []
    completed: set[str] = set()
    while len(completed) < len(ordered):
        ready = [
            step
            for step in ordered
            if step.step_id not in completed and dependencies[step.step_id] <= completed
        ]
        if not ready:
            blocked = sorted(step_id for step_id in by_id if step_id not in completed)
            raise ValueError(f"Workflow contains a dependency cycle: {', '.join(blocked)}")
        batches.append(ready)
        completed.update(step.step_id for step in ready)
    return batches

