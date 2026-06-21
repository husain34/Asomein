"""
asomien/agents/base_agent.py

Abstract base class for all agents in the Asomien system.

Provides:
  - Abstract run() / stop() lifecycle hooks
  - log_action() for consistent structured audit logging
  - safe start/stop lifecycle management
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional


logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base for all Asomien agents.

    Subclasses MUST implement:
        run()  — the agent's main execution loop
        stop() — graceful shutdown (set self._running = False, clean up)

    Subclasses SHOULD call super().__init__() and may pass additional
    kwargs for dependency injection.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        self.name: str = name or self.__class__.__name__
        self._running: bool = False
        logger.info("[%s] Initialised.", self.name)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abstractmethod
    def run(self) -> None:
        """
        Main execution entry-point.
        For scheduled agents: call once per trigger.
        For loop agents: run until self._running is False.
        """

    def stop(self) -> None:
        """
        Graceful shutdown. Sets _running to False.
        Subclasses may override to add cleanup, but should call super().stop().
        """
        self._running = False
        logger.info("[%s] Stop requested.", self.name)

    def start(self) -> None:
        """Mark the agent as running. Call before run()."""
        self._running = True
        logger.info("[%s] Started.", self.name)

    # ── Audit logging ─────────────────────────────────────────────────────────

    def log_action(
        self,
        action: str,
        reason: str,
        outcome: Any = None,
        level: str = "info",
    ) -> None:
        """
        Structured audit log. Every agent action should call this.
        """
        import json
        import os
        
        ts = datetime.now(timezone.utc).isoformat()
        msg = (
            f"[{self.name}] action={action!r} reason={reason!r} "
            f"outcome={outcome!r} ts={ts}"
        )
        getattr(logger, level, logger.info)(msg)
        
        # Append structured JSON to logs/actions.log
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "actions.log")
        
        log_entry = {
            "timestamp": ts,
            "agent": self.name,
            "action": action,
            "reason": reason,
            "outcome": str(outcome) if outcome is not None else None,
            "level": level
        }
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.error("[%s] Failed to write to actions.log: %s", self.name, e)
