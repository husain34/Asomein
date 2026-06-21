"""
asomien/platforms/base_platform.py

Abstract base class for platform adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BasePlatformAdapter(ABC):
    """Contract for platform-specific publishing and analytics adapters."""

    @abstractmethod
    def publish_text_post(self, text: str, **kwargs: Any) -> str:
        """Publish a text post and return the platform post id."""

    @abstractmethod
    def publish_reply(self, text: str, parent_post_id: str, **kwargs: Any) -> str:
        """Publish a reply to an existing post and return the created post id."""

    @abstractmethod
    def delete_post(self, post_id: str, **kwargs: Any) -> bool:
        """Delete a post and return whether the action succeeded."""

    @abstractmethod
    def get_post_metrics(self, post_id: str, **kwargs: Any) -> dict[str, Any]:
        """Fetch metrics for a post."""

    @abstractmethod
    def get_audience_insights(self, **kwargs: Any) -> dict[str, Any]:
        """Fetch audience-level insights."""

    @abstractmethod
    def get_publishing_quota(self, **kwargs: Any) -> dict[str, Any]:
        """Fetch publishing quota / rate-limit information."""
