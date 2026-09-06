# -*- coding: utf-8 -*-
import pytest

from app.core.orchestrator.dag import topological_batches
from app.domain.contracts import WorkflowStep


def step(step_id: str, order: int, depends_on: list[str] | None = None) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        order=order,
        subtask_id=step_id,
        skill_name="copywriter",
        skill_reason="test",
        goal="test",
        depends_on=depends_on or [],
    )


def test_dag_groups_independent_steps_for_parallel_execution() -> None:
    batches = topological_batches(
        [
            step("search-a", 1),
            step("search-b", 2),
            step("write", 3, ["search-a", "search-b"]),
        ]
    )

    assert [[item.step_id for item in batch] for batch in batches] == [
        ["search-a", "search-b"],
        ["write"],
    ]


def test_dag_rejects_cycles_before_execution() -> None:
    with pytest.raises(ValueError, match="dependency cycle"):
        topological_batches([step("a", 1, ["b"]), step("b", 2, ["a"])])

