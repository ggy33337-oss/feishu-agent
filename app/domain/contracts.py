# -*- coding: utf-8 -*-
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, NotRequired, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskType(str, Enum):
    EXCEL = "excel"
    PPT = "ppt"
    COPYWRITER = "copywriter"
    IMAGE = "image"
    SEARCH = "search"
    GENERAL = "general"


class TaskSubtask(BaseModel):
    subtask_id: str = Field(default_factory=lambda: str(uuid4()))
    order: int = Field(ge=1)
    goal: str
    task_type: TaskType
    normalized_text: str
    dependencies: list[str] = Field(default_factory=list)
    expected_output: str | None = None
    hints: list[str] = Field(default_factory=list)


class TaskExtraction(BaseModel):
    execution_mode: Literal["direct", "workflow"] = "workflow"
    task_type: TaskType
    user_intent: str
    normalized_text: str
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    subtasks: list[TaskSubtask] = Field(default_factory=list)


class RouteDecision(BaseModel):
    """Intent Router output; detailed tool parameters are analyzed separately."""

    mode: Literal["direct", "tool"] = "tool"
    answer: str | None = None
    skill_name: str | None = None
    skill_reason: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_summary: bool = False

    @model_validator(mode="after")
    def validate_route(self) -> "RouteDecision":
        if self.mode == "direct" and not str(self.answer or "").strip():
            raise ValueError("answer is required for a direct route")
        if self.mode == "tool" and not str(self.skill_name or "").strip():
            raise ValueError("skill_name is required for a tool route")
        return self


class StructuredTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    execution_mode: Literal["direct", "workflow"] = "workflow"
    task_type: TaskType
    user_intent: str
    normalized_text: str
    source_text: str = ""
    user_id: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    reply_token: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    subtasks: list[TaskSubtask] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    route_skill: str | None = None
    route_parameters: dict[str, Any] = Field(default_factory=dict)
    route_answer: str | None = None
    route_reason: str = ""
    route_requires_summary: bool = False


class WorkflowStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    order: int = Field(ge=1)
    subtask_id: str
    skill_name: str
    skill_reason: str
    goal: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_output: str | None = None


class WorkflowPlan(BaseModel):
    mode: Literal["direct", "workflow"]
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    answer: str | None = None
    subtasks: list[TaskSubtask] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_plan(self) -> "WorkflowPlan":
        if self.mode == "direct" and not self.answer:
            raise ValueError("answer is required when mode is direct")
        if self.mode == "workflow" and not self.steps:
            raise ValueError("steps are required when mode is workflow")
        return self


class WorkflowAssessment(BaseModel):
    intent_satisfied: bool
    rationale: str
    answer: str = Field(min_length=1)
    missing_information: list[str] = Field(default_factory=list)


class ResearchAction(BaseModel):
    type: Literal["tool_call", "complete"]
    reason: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    accepted_urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action(self) -> "ResearchAction":
        if self.type == "tool_call" and not str(self.arguments.get("query") or "").strip():
            raise ValueError("arguments.query is required for a research tool call")
        if self.type == "complete":
            self.arguments = {}
        return self


class SkillArtifact(TypedDict):
    type: str
    path: str
    name: NotRequired[str | None]
    mime_type: NotRequired[str | None]


class SkillContext(BaseModel):
    """Typed cross-skill execution context with controlled extension fields."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    text: str = ""
    source_text: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    user_id: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    task_type: str = "general"
    user_intent: str = ""
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    step: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dependency_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    previous_outputs: list[dict[str, Any]] = Field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_executor_input(self) -> dict[str, Any]:
        return self.model_dump()


class Plan(BaseModel):
    task_id: str
    step_id: str
    subtask_id: str
    skill_name: str
    steps: list[str]
    inputs: SkillContext


class SkillResult(BaseModel):
    ok: bool
    message: str
    artifacts: list[SkillArtifact] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class QueueJob(BaseModel):
    job_id: str
    kind: str
    payload: dict[str, Any]
    status: Literal["pending", "running", "retry", "completed", "dead"]
    attempts: int = 0
    result: dict[str, Any] | None = None
    last_error: str | None = None
    created_at: float
    updated_at: float
