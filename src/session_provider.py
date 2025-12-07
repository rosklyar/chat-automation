"""Session provider protocol and implementations."""

from pathlib import Path
from typing import Protocol, Optional, runtime_checkable

from .models import SessionType, SessionInfo


@runtime_checkable
class SessionProvider(Protocol):
    """
    Protocol for providing and managing AI assistant sessions.

    Sessions are authentication states that can be loaded into a browser
    context to access AI assistants without manual login.

    The provider tracks usage and handles rotation when sessions reach
    their usage limits.
    """

    def get_session(self, session_type: SessionType) -> Optional[SessionInfo]:
        """
        Get an available session for the specified type.

        Args:
            session_type: The type of AI provider session needed.

        Returns:
            SessionInfo if an available session exists, None otherwise.

        Note:
            This method selects the next available session but does NOT
            increment the usage counter. Call `record_evaluation()` after
            successfully using the session.
        """
        ...

    def record_evaluation(self, session_id: str) -> int:
        """
        Record that an evaluation was performed with a session.

        This increments the usage counter for the session and returns
        the number of evaluations remaining before rotation is needed.

        Args:
            session_id: The ID of the session that was used.

        Returns:
            Number of evaluations remaining (0 means rotation needed).

        Raises:
            KeyError: If session_id is not found.
        """
        ...

    def mark_invalid(self, session_id: str) -> None:
        """
        Mark a session as invalid (expired, rate-limited, etc.).

        Invalid sessions will not be returned by `get_session()`.

        Args:
            session_id: The ID of the session to invalidate.
        """
        ...

    def reset_session(self, session_id: str) -> None:
        """
        Reset a session's usage counter.

        Called when cycling back to a session after rotation.

        Args:
            session_id: The ID of the session to reset.
        """
        ...

    @property
    def available_session_count(self) -> int:
        """Number of valid sessions available for use."""
        ...


class FileSessionProvider:
    """
    Session provider that loads sessions from JSON files in a directory.

    Sessions are stored as Playwright storage state JSON files.
    The provider cycles through sessions in round-robin fashion.
    """

    def __init__(
        self,
        sessions_dir: Path | str,
        session_type: SessionType = SessionType.CHATGPT,
        max_usage_per_session: int = 10,
    ) -> None:
        """
        Initialize the file-based session provider.

        Args:
            sessions_dir: Directory containing session .json files.
            session_type: Type of sessions in this directory.
            max_usage_per_session: Number of evaluations before rotation.

        Raises:
            FileNotFoundError: If sessions_dir doesn't exist.
            ValueError: If no .json files found in directory.
        """
        self._sessions_dir = Path(sessions_dir)
        self._session_type = session_type
        self._max_usage = max_usage_per_session
        self._sessions: dict[str, SessionInfo] = {}
        self._rotation_order: list[str] = []
        self._current_index: int = 0

        self._load_sessions()

    def _load_sessions(self) -> None:
        """Load session files from directory."""
        if not self._sessions_dir.exists():
            raise FileNotFoundError(f"Sessions directory not found: {self._sessions_dir}")

        if not self._sessions_dir.is_dir():
            raise ValueError(f"Path is not a directory: {self._sessions_dir}")

        session_files = sorted(self._sessions_dir.glob("*.json"))
        if not session_files:
            raise ValueError(f"No .json session files in {self._sessions_dir}")

        for file_path in session_files:
            session_id = file_path.stem  # filename without extension
            self._sessions[session_id] = SessionInfo(
                session_id=session_id,
                session_type=self._session_type,
                file_path=str(file_path),
                max_usage=self._max_usage,
            )
            self._rotation_order.append(session_id)

        print(f"Loaded {len(self._sessions)} session(s) from {self._sessions_dir}:")
        for idx, session_id in enumerate(self._rotation_order, 1):
            print(f"  {idx}. {session_id}")

    def get_session(self, session_type: SessionType) -> Optional[SessionInfo]:
        """Get the next available session in rotation order."""
        if session_type != self._session_type:
            return None

        # Find next valid session
        attempts = 0
        while attempts < len(self._rotation_order):
            session_id = self._rotation_order[self._current_index]
            session = self._sessions[session_id]

            if session.is_valid and not session.needs_rotation:
                return session

            # If session needs rotation but is valid, reset it when cycling
            if session.is_valid and session.needs_rotation:
                session.usage_count = 0
                return session

            # Try next session
            self._current_index = (self._current_index + 1) % len(self._rotation_order)
            attempts += 1

        return None  # No valid sessions available

    def record_evaluation(self, session_id: str) -> int:
        """Record an evaluation and return remaining count."""
        if session_id not in self._sessions:
            raise KeyError(f"Unknown session: {session_id}")

        session = self._sessions[session_id]
        session.usage_count += 1

        remaining = session.evaluations_remaining

        # If exhausted, advance to next session
        if remaining == 0:
            self._current_index = (self._current_index + 1) % len(self._rotation_order)

        return remaining

    def mark_invalid(self, session_id: str) -> None:
        """Mark session as invalid."""
        if session_id in self._sessions:
            self._sessions[session_id].is_valid = False
            # Advance to next session
            self._current_index = (self._current_index + 1) % len(self._rotation_order)

    def reset_session(self, session_id: str) -> None:
        """Reset session usage counter."""
        if session_id in self._sessions:
            self._sessions[session_id].usage_count = 0

    @property
    def available_session_count(self) -> int:
        """Count of valid sessions."""
        return sum(1 for s in self._sessions.values() if s.is_valid)
