"""WebSocket connection session identity."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .timestamps import utc_now_iso


@dataclass
class ConnectionSession:
    connection_session_id: str
    reconnect_generation: int
    connected_at: str
    disconnected_at: Optional[str] = None
    disconnect_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_session_id": self.connection_session_id,
            "reconnect_generation": self.reconnect_generation,
            "connected_at": self.connected_at,
            "disconnected_at": self.disconnected_at,
            "disconnect_reason": self.disconnect_reason,
        }


@dataclass
class SessionManager:
    reconnect_generation: int = 0
    current: Optional[ConnectionSession] = None
    history: list[ConnectionSession] = field(default_factory=list)

    def begin_session(self) -> ConnectionSession:
        if self.current is not None and self.current.disconnected_at is None:
            self.end_session("superseded_by_new_session")
        self.reconnect_generation += 1
        session = ConnectionSession(
            connection_session_id=str(uuid.uuid4()),
            reconnect_generation=self.reconnect_generation,
            connected_at=utc_now_iso(),
        )
        self.current = session
        return session

    def end_session(self, reason: str) -> Optional[ConnectionSession]:
        if self.current is None:
            return None
        self.current.disconnected_at = utc_now_iso()
        self.current.disconnect_reason = reason
        self.history.append(self.current)
        ended = self.current
        self.current = None
        return ended
