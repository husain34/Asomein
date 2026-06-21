"""
asomien/platforms/threads_adapter.py

Threads platform adapter implementing the required publish flow.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

from asomien.platforms.base_platform import BasePlatformAdapter

logger = logging.getLogger(__name__)

_THREADS_API_BASE = "https://graph.threads.net/v1.0"


class ThreadsAdapter(BasePlatformAdapter):
    """Adapter for the Threads Graph API.

    Publish flow:
      1. POST /me/threads to create a text container.
      2. Sleep 2 seconds.
      3. POST /me/threads_publish to make it live.
    """

    def __init__(
        self,
        access_token: str,
        user_id: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: int = 10,
    ) -> None:
        self.access_token = access_token
        self.user_id = user_id or "me"
        self.session = session or requests.Session()
        self.timeout = timeout

    def _build_url(self, endpoint: str) -> str:
        if endpoint.startswith("https://"):
            return endpoint
        return f"{_THREADS_API_BASE}/{endpoint}"

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        retry: int = 3,
    ) -> dict[str, Any]:
        last_error: Optional[Exception] = None
        current_delay = 1
        request_fn = getattr(self.session, method.lower())

        for attempt in range(retry):
            try:
                response = request_fn(
                    self._build_url(endpoint),
                    params=params,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected JSON object from Threads API")

                error_info = payload.get("error")
                if error_info:
                    if isinstance(error_info, dict):
                        message = error_info.get("message", str(error_info))
                    else:
                        message = str(error_info)
                    raise requests.HTTPError(
                        f"Threads API error: {message}"
                    )

                return payload
            except requests.RequestException as exc:
                last_error = exc
                if attempt == retry - 1:
                    raise
                logger.warning(
                    "Threads API request failed (attempt %s/%s): %s",
                    attempt + 1,
                    retry,
                    exc,
                )
                time.sleep(current_delay)
                current_delay *= 2

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unreachable request error path")

    def _publish_with_container(
        self,
        text: str,
        reply_to_id: Optional[str] = None,
    ) -> str:
        container_payload = self._request(
            method="POST",
            endpoint="me/threads",
            params={
                "access_token": self.access_token,
                "media_type": "TEXT",
                "text": text,
                **({"reply_to_id": reply_to_id} if reply_to_id else {}),
            },
        )
        container_id = str(
            container_payload.get("id")
            or container_payload.get("container_id")
            or ""
        )
        if not container_id:
            raise ValueError("Threads API did not return a container id")

        time.sleep(2)

        publish_payload = self._request(
            method="POST",
            endpoint="me/threads_publish",
            params={
                "access_token": self.access_token,
                "creation_id": container_id,
            },
        )
        post_id = str(
            publish_payload.get("id")
            or publish_payload.get("post_id")
            or ""
        )
        if not post_id:
            raise ValueError("Threads API did not return a post id")
        return post_id

    def publish_text_post(self, text: str, **kwargs: Any) -> str:
        return self._publish_with_container(
            text=text,
            reply_to_id=kwargs.get("reply_to_id"),
        )

    def publish_reply(self, text: str, parent_post_id: str, **kwargs: Any) -> str:
        return self._publish_with_container(
            text=text,
            reply_to_id=parent_post_id,
        )

    def delete_post(self, post_id: str, **kwargs: Any) -> bool:
        payload = self._request(
            method="POST",
            endpoint=f"{self.user_id}/delete_post",
            params={
                "access_token": self.access_token,
                "post_id": post_id,
            },
        )
        return bool(
            payload.get("success")
            or payload.get("deleted")
            or payload.get("status") == "success"
        )

    def get_post_metrics(self, post_id: str, **kwargs: Any) -> dict[str, Any]:
        payload = self._request(
            method="GET",
            endpoint=f"{post_id}/insights",
            params={
                "access_token": self.access_token,
                **kwargs,
            },
        )
        return payload

    def get_audience_insights(self, **kwargs: Any) -> dict[str, Any]:
        payload = self._request(
            method="GET",
            endpoint=f"{self.user_id}/insights",
            params={
                "access_token": self.access_token,
                **kwargs,
            },
        )
        return payload

    def get_profile(self, **kwargs: Any) -> dict[str, Any]:
        payload = self._request(
            method="GET",
            endpoint=f"{self.user_id}",
            params={
                "access_token": self.access_token,
                **kwargs,
            },
        )
        return payload

    def get_publishing_quota(self, **kwargs: Any) -> dict[str, Any]:
        return self.get_audience_insights(**kwargs)

    def get_mentions(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch recent replies/mentions directed at this account."""
        try:
            payload = self._request(
                method="GET",
                endpoint=f"{self.user_id}/replies",
                params={
                    "access_token": self.access_token,
                    **kwargs,
                },
            )
            return payload.get("data", [])
        except requests.HTTPError as e:
            logger.warning("Failed to fetch mentions/replies from Threads API: %s", e)
            return []

