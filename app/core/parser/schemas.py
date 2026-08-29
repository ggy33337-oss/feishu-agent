from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class TaskType(str, Enum):
    EXCEL = "excel"
    PPT = "ppt"
    COPYWRITER = "copywriter"
    IMAGE = "image"
    SEARCH = "search"
    GENERAL = "general"


class TaskExtraction(BaseModel):
    task_type: TaskType
    user_intent: str
    normalized_text: str
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class StructuredTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    task_type: TaskType
    user_intent: str
    normalized_text: str
    user_id: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    reply_token: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class RouteDecision(BaseModel):
    mode: Literal["tool", "direct"]
    skill_name: str | None = None
    answer: str | None = None
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_route(self) -> "RouteDecision":
        if self.mode == "tool" and not self.skill_name:
            raise ValueError("skill_name is required when mode is tool")
        if self.mode == "direct" and not self.answer:
            raise ValueError("answer is required when mode is direct")
        return self


SkillDecision = RouteDecision


class Plan(BaseModel):
    task_id: str
    skill_name: str
    steps: list[str]
    inputs: dict[str, Any] = Field(default_factory=dict)


class SkillResult(BaseModel):
    ok: bool
    message: str
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
