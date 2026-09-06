# -*- coding: utf-8 -*-
"""Canonical pipeline stage names.

The architecture intentionally has a small vocabulary.  Individual skills can
still expose provider-specific details through event fields, while dashboards
can aggregate by these stable names.
"""

from __future__ import annotations


class PipelineStage:
    """Stable stage names for the intent/chat and tool-call paths."""

    INTENT_ROUTER = "intent.route"
    CHAT_MODEL = "chat.model"
    SKILL_ROUTER = "skill.route"
    TOOL_ANALYZE = "tool.analyze"
    SKILL = "skill.execute"
    TOOL = "tool.execute"
    RESULT_MODEL = "result.process"
