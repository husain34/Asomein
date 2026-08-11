"""
asomien/memory/nodes.py

All dataclasses / Pydantic models for the TRACE-XP memory system.
Corresponds to the memory node types defined in Section 3 of the blueprint.

These models are used both for in-memory representation and for
serialization to/from SQLite (via the MemoryEngine).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator


def _new_uuid() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def _now_utc() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


# ── TopicNode ─────────────────────────────────────────────────────────────────

class TopicNode(BaseModel):
    """
    Represents a topic/sub-niche in the experience tree.
    Examples: 'phone brain', '3am energy', 'AI self-awareness'.
    """

    id: str = Field(default_factory=_new_uuid)
    name: str
    parent_id: Optional[str] = None
    relevance_score: float = 0.5        # 0.0–1.0; updated by analytics
    niche_alignment: float = 0.5        # 0.0–1.0; how well this fits the persona
    last_researched: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now_utc)

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("relevance_score", "niche_alignment", mode="before")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


# ── ResearchNode ──────────────────────────────────────────────────────────────

class ResearchNode(BaseModel):
    """
    Stores a single research finding — a meme format or cultural moment.

    cultural_freshness decays faster than standard research (48h vs 72h).
    meme_format_detected maps to one of the HOOK_TEMPLATES ids.
    """

    id: str = Field(default_factory=_new_uuid)
    topic_id: Optional[str] = None
    source: str                         # 'reddit' | 'tumblr_rss' | 'knowyourmeme' | 'duckduckgo' | 'threads_keyword'
    headline: str = ""
    summary: str = ""
    raw_url: str = ""
    meme_format_detected: str = ""      # e.g. 'toxic_trait', 'pipeline'
    cultural_freshness: int = 80        # 0–100; decays faster than standard research
    discovered_at: datetime = Field(default_factory=_now_utc)
    expiry: Optional[datetime] = None   # 48h for meme; 72h for standard
    is_active: bool = True

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("cultural_freshness", mode="before")
    @classmethod
    def clamp_freshness(cls, v: int) -> int:
        return max(0, min(100, int(v)))

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, v: str) -> str:
        valid = {"reddit", "tumblr_rss", "knowyourmeme", "duckduckgo", "threads_keyword"}
        if v not in valid:
            # Accept unknown sources but normalize — don't crash on new sources
            return v.lower().strip()
        return v


# ── PostNode ──────────────────────────────────────────────────────────────────

class PostNode(BaseModel):
    """
    Represents a post at any lifecycle stage: draft → queued → published | failed.
    Tracks T_jitter values for audit trail.
    """

    id: str = Field(default_factory=_new_uuid)
    topic_id: Optional[str] = None
    platform: str = "threads"
    content: str                        # ≤500 characters; lowercase
    post_type: str = "text"             # 'text' | 'image' | 'carousel' | 'reply'
    hook_template_used: str = ""        # tracks template ID for rotation enforcement
    status: str = "draft"               # 'draft' | 'queued' | 'published' | 'failed'
    scheduled_publish_time: Optional[datetime] = None
    actual_publish_time: Optional[datetime] = None
    jitter_offset_minutes: int = 0      # T_jitter value applied (for audit)
    posted_at: Optional[datetime] = None
    threads_post_id: str = ""
    threads_container_id: str = ""
    permalink: str = ""
    is_reply: bool = False
    reply_to_threads_id: str = ""
    is_sponsored: bool = False
    sponsor_campaign_id: str = ""
    pre_score: Optional[dict[str, Any]] = None   # CritiqueScore dict
    summary: str = ""
    created_at: datetime = Field(default_factory=_now_utc)

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: str) -> str:
        valid = {"draft", "queued", "published", "failed"}
        if v not in valid:
            raise ValueError(f"Invalid post status: {v}. Must be one of {valid}")
        return v

    @field_validator("post_type", mode="before")
    @classmethod
    def validate_post_type(cls, v: str) -> str:
        valid = {"text", "image", "carousel", "reply"}
        if v not in valid:
            raise ValueError(f"Invalid post type: {v}. Must be one of {valid}")
        return v

    @property
    def char_count(self) -> int:
        return len(self.content)

    @property
    def is_over_limit(self) -> bool:
        return self.char_count > 500

    @property
    def is_lowercase_compliant(self) -> bool:
        """First character of the post must not be uppercase."""
        stripped = self.content.lstrip()
        if not stripped:
            return False
        # Allow digits, emojis, punctuation — only block uppercase letters
        return not stripped[0].isupper()


# ── MetricsSnapshot ───────────────────────────────────────────────────────────

class MetricsSnapshot(BaseModel):
    """
    Point-in-time snapshot of a post's engagement metrics.
    Stored in metrics.db. Multiple snapshots per post (30min, 24h, 7d).
    """

    id: str = Field(default_factory=_new_uuid)
    post_id: str
    threads_post_id: str = ""
    snapshot_time: datetime = Field(default_factory=_now_utc)
    views: int = 0
    likes: int = 0
    replies: int = 0
    reposts: int = 0
    quotes: int = 0
    shares: int = 0
    creator_engagement_score: float = 0.0

    model_config = {"arbitrary_types_allowed": True}

    @property
    def weighted_engagement(self) -> float:
        """
        Weighted engagement using the algorithm signal hierarchy from the blueprint:
        - author_reply_to_own_post: 150× (tracked separately)
        - reply from another user:  27×
        - quote:                     8×
        - repost:                    5×
        - like:                      1×
        """
        return (
            self.replies * 27
            + self.quotes * 8
            + self.reposts * 5
            + self.likes * 1
        )


# ── ReflectionNode ────────────────────────────────────────────────────────────

class ReflectionNode(BaseModel):
    """
    Post-hoc analysis of a published post. Generated by the Critic Agent.
    Used by the learning system (Phase 8+) to evolve rules.
    Stored in memory.db / reflections table.
    """

    id: str = Field(default_factory=_new_uuid)
    post_id: str
    hook_template_used: str = ""
    sub_niche: str = ""
    generated_at: datetime = Field(default_factory=_now_utc)
    success_factors: list[str] = Field(default_factory=list)
    failure_factors: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    confidence: float = 0.5

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


# ── RuleNode ──────────────────────────────────────────────────────────────────

class RuleNode(BaseModel):
    """
    An empirically derived posting rule. Requires 3+ evidence examples before
    creation. Confidence decays if no new supporting evidence is found.
    Part of the V2 learning system (Phase 8+).
    """

    id: str = Field(default_factory=_new_uuid)
    rule_text: str
    confidence: float = 0.5
    evidence: list[str] = Field(default_factory=list)    # post_ids that support this rule
    created_at: datetime = Field(default_factory=_now_utc)
    last_validated: Optional[datetime] = None
    validation_count: int = 0
    decay_rate: float = 0.05    # confidence decay per validation cycle without evidence
    is_active: bool = True

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


# ── CritiqueScore ─────────────────────────────────────────────────────────────

class CritiqueScore(BaseModel):
    """
    Result of CriticAgent.pre_publish_critique().
    Contains composite score, per-dimension breakdown, and rejection details.
    Corresponds to Section 5 / critic_agent.py in the blueprint.
    """

    # Composite score (weighted average of 6 dimensions)
    composite: float = 0.0

    # Per-dimension scores
    hook_strength: float = 0.0          # weight: 0.30
    reply_bait_score: float = 0.0       # weight: 0.25
    persona_authenticity: float = 0.0   # weight: 0.20
    format_recognition: float = 0.0     # weight: 0.10
    conversational_tone: float = 0.0    # weight: 0.10
    novelty_score: float = 0.0          # weight: 0.05

    # Hard gate result
    passed_hard_gates: bool = True
    rejection_reason: Optional[str] = None   # set if any hard gate or min threshold fails
    is_approved: bool = False

    model_config = {"arbitrary_types_allowed": True}

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def hard_reject(cls, reason: str) -> "CritiqueScore":
        """Factory: create a definitively rejected score with a reason."""
        return cls(
            composite=0.0,
            passed_hard_gates=False,
            rejection_reason=reason,
            is_approved=False,
        )


# ── AudienceSnapshot ──────────────────────────────────────────────────────────

class AudienceSnapshot(BaseModel):
    """
    Account-level metrics snapshot collected every 6 hours.
    Stored in metrics.db / audience_snapshots table.
    """

    id: str = Field(default_factory=_new_uuid)
    snapshot_time: datetime = Field(default_factory=_now_utc)
    followers_count: int = 0
    profile_views: int = 0
    link_clicks: int = 0
    total_likes: int = 0
    total_replies: int = 0
    total_reposts: int = 0
    total_quotes: int = 0

    model_config = {"arbitrary_types_allowed": True}


# ── DirectiveNode ─────────────────────────────────────────────────────────────

class DirectiveNode(BaseModel):
    """
    Human-issued directive to the orchestrator.
    Stored in directives.db / directives table.
    Examples: 'focus on 3am energy posts today', 'skip today's publish'
    """

    id: str = Field(default_factory=_new_uuid)
    directive_type: str                  # 'topic_focus' | 'skip_publish' | 'emergency_stop' | 'custom'
    content: str = ""
    priority: int = 5                    # 1–10; 10 = highest
    status: str = "active"              # 'active' | 'completed' | 'cancelled'
    start_time: datetime = Field(default_factory=_now_utc)
    end_time: Optional[datetime] = None
    metadata: Optional[dict[str, Any]] = None

    model_config = {"arbitrary_types_allowed": True}
