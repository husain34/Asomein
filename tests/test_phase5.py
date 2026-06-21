from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestThreadsAdapterPublishFlow:
    def test_publish_text_post_uses_two_step_pipeline_in_order(self):
        from asomien.platforms.threads_adapter import ThreadsAdapter

        response_container = MagicMock()
        response_container.status_code = 200
        response_container.json.return_value = {"id": "container-123"}

        response_publish = MagicMock()
        response_publish.status_code = 200
        response_publish.json.return_value = {"id": "post-456"}

        session = MagicMock()
        session.post.side_effect = [response_container, response_publish]

        adapter = ThreadsAdapter(
            access_token="token-123",
            user_id="user-456",
            session=session,
        )

        with patch("asomien.platforms.threads_adapter.time.sleep") as sleep_mock:
            result = adapter.publish_text_post("hello from tests")

        assert result == "post-456"
        assert session.post.call_count == 2
        assert session.post.call_args_list[0].args[0].endswith("/me/threads")
        assert session.post.call_args_list[1].args[0].endswith("/me/threads_publish")
        assert session.post.call_args_list[0].kwargs["params"]["text"] == "hello from tests"
        assert session.post.call_args_list[1].kwargs["params"]["creation_id"] == "container-123"
        sleep_mock.assert_any_call(2)

    def test_timeout_errors_trigger_backoff_retries(self):
        from asomien.platforms.threads_adapter import ThreadsAdapter

        response_container = MagicMock()
        response_container.status_code = 200
        response_container.json.return_value = {"id": "container-999"}

        response_publish = MagicMock()
        response_publish.status_code = 200
        response_publish.json.return_value = {"id": "post-999"}

        session = MagicMock()
        session.post.side_effect = [
            requests.Timeout(),
            requests.Timeout(),
            response_container,
            response_publish,
        ]

        adapter = ThreadsAdapter(
            access_token="token-123",
            user_id="user-456",
            session=session,
        )

        with patch("asomien.platforms.threads_adapter.time.sleep") as sleep_mock:
            result = adapter.publish_text_post("retry me")

        assert result == "post-999"
        assert session.post.call_count == 4
        assert sleep_mock.call_args_list[0] == call(1)
        assert sleep_mock.call_args_list[1] == call(2)
        assert sleep_mock.call_args_list[2] == call(2)

    def test_error_payload_raises_exception_even_with_200_status(self):
        from asomien.platforms.threads_adapter import ThreadsAdapter

        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "error": {"message": "Token expired"}
        }

        session = MagicMock()
        session.get.return_value = response

        adapter = ThreadsAdapter(
            access_token="token-123",
            user_id="user-456",
            session=session,
        )

        with pytest.raises(requests.HTTPError, match="Token expired"):
            adapter.get_profile()


class TestAnalyticsAgent:
    def test_collect_post_metrics_stores_creator_engagement_score(self, tmp_path):
        from asomien.agents.analytics_agent import AnalyticsAgent

        adapter = MagicMock()
        adapter.get_post_metrics.return_value = {
            "id": "thread-123",
            "views": 100,
            "likes": 10,
            "replies": 2,
            "reposts": 1,
            "quotes": 1,
            "shares": 0,
        }

        db_path = tmp_path / "metrics.db"
        agent = AnalyticsAgent(
            adapter=adapter,
            metrics_db_path=str(db_path),
        )

        agent.collect_post_metrics(
            SimpleNamespace(
                id="post-1",
                threads_post_id="thread-123",
            )
        )

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT post_id, threads_post_id, views, likes, replies, reposts, quotes, shares, creator_engagement_score FROM post_metrics"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        assert row[0] == "post-1"
        assert row[1] == "thread-123"
        assert row[2] == 100
        assert row[3] == 10
        assert row[4] == 2
        assert row[5] == 1
        assert row[6] == 1
        assert row[7] == 0
        assert row[8] == pytest.approx((10 * 1 + 2 * 27 + 1 * 5 + 1 * 8) / 100)

    def test_collect_post_metrics_parses_meta_nested_insights_payload(self, tmp_path):
        from asomien.agents.analytics_agent import AnalyticsAgent

        adapter = MagicMock()
        adapter.get_post_metrics.return_value = {
            "data": [
                {"name": "views", "values": [{"value": 150}]},
                {"name": "likes", "values": [{"value": 12}]},
                {"name": "replies", "values": [{"value": 3}]},
                {"name": "reposts", "values": [{"value": 1}]},
                {"name": "quotes", "values": [{"value": 2}]},
                {"name": "shares", "values": [{"value": 1}]},
            ]
        }

        db_path = tmp_path / "metrics.db"
        agent = AnalyticsAgent(
            adapter=adapter,
            metrics_db_path=str(db_path),
        )

        snapshot = agent.collect_post_metrics(
            SimpleNamespace(
                id="post-2",
                threads_post_id="thread-456",
            )
        )

        assert snapshot.views == 150
        assert snapshot.likes == 12
        assert snapshot.replies == 3
        assert snapshot.reposts == 1
        assert snapshot.quotes == 2
        assert snapshot.shares == 1
        assert snapshot.creator_engagement_score == pytest.approx(
            (12 * 1 + 3 * 27 + 1 * 5 + 2 * 8) / 150
        )
