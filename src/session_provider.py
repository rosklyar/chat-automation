"""Session provider protocol and implementations."""

import json
import logging
from pathlib import Path
from typing import Protocol, Optional, runtime_checkable

from .models import EvaluationRecorded

logger = logging.getLogger(__name__)


@runtime_checkable
class SessionProvider(Protocol):
    """
    Protocol for providing and managing AI assistant sessions.

    Sessions are authentication states (StorageState dicts) that can be
    loaded into a browser context to access AI assistants without manual login.

    The provider tracks the current session internally and handles
    rotation automatically when usage limits are reached.
    """

    def get_session(self) -> Optional[dict]:
        """
        Get StorageState dict of the current session.

        Returns:
            Dict with 'cookies' and 'origins' keys (Playwright StorageState format),
            or None if no valid sessions available.

        StorageState format:
            {
                "cookies": [{"name": "...", "value": "...", "domain": "...", ...}],
                "origins": [{"origin": "...", "localStorage": [...]}]
            }
        """
        ...

    def record_evaluation(self) -> EvaluationRecorded:
        """
        Record that an evaluation was performed with the current session.

        Increments usage counter. When exhausted, automatically rotates
        to the next session.

        Returns:
            EvaluationRecorded with:
            - remaining: Number of evaluations remaining on current session
            - rotated: True if session was auto-rotated (browser needs reset)
        """
        ...

    def force_rotate(self) -> None:
        """
        Force switch to the next session.

        Use when current session is rate-limited or not returning citations.
        The current session is reset and remains in the rotation pool.
        """
        ...

    @property
    def has_sessions(self) -> bool:
        """Check if any sessions are available."""
        ...

    @property
    def current_session_name(self) -> Optional[str]:
        """Name of current session for logging (e.g., 'account1')."""
        ...


class FileSessionProvider:
    """
    Session provider that loads sessions from JSON files in a directory.

    Sessions are stored as Playwright storage state JSON files.
    The provider loads them into memory and cycles through in round-robin fashion.
    """

    def __init__(
        self,
        sessions_dir: Path | str,
        max_usage_per_session: int = 10,
    ) -> None:
        """
        Initialize the file-based session provider.

        Args:
            sessions_dir: Directory containing session .json files.
            max_usage_per_session: Number of evaluations before rotation.

        Raises:
            FileNotFoundError: If sessions_dir doesn't exist.
            ValueError: If no .json files found in directory.
        """
        self._sessions_dir = Path(sessions_dir)
        self._max_usage = max_usage_per_session
        self._sessions: list[dict] = []  # List of StorageState dicts
        self._session_names: list[str] = []  # Corresponding names
        self._current_index: int = 0
        self._usage_count: int = 0

        self._load_sessions()

    def _load_sessions(self) -> None:
        """Load session files from directory into memory."""
        if not self._sessions_dir.exists():
            raise FileNotFoundError(f"Sessions directory not found: {self._sessions_dir}")

        if not self._sessions_dir.is_dir():
            raise ValueError(f"Path is not a directory: {self._sessions_dir}")

        session_files = sorted(self._sessions_dir.glob("*.json"))
        if not session_files:
            raise ValueError(f"No .json session files in {self._sessions_dir}")

        for file_path in session_files:
            with open(file_path, 'r', encoding='utf-8') as f:
                storage_state = json.load(f)
                self._sessions.append(storage_state)
                self._session_names.append(file_path.stem)

        logger.info(f"Loaded {len(self._sessions)} session(s)")

    def get_session(self) -> Optional[dict]:
        """Get StorageState dict of the current session."""
        if not self._sessions:
            return None
        return self._sessions[self._current_index]

    def record_evaluation(self) -> EvaluationRecorded:
        """Record an evaluation and return result with rotation flag."""
        self._usage_count += 1
        remaining = self._max_usage - self._usage_count
        rotated = False

        if remaining <= 0:
            # Auto-rotate to next session
            self._rotate()
            remaining = self._max_usage
            rotated = True

        return EvaluationRecorded(remaining=remaining, rotated=rotated)

    def force_rotate(self) -> None:
        """Force switch to the next session."""
        self._rotate()

    def _rotate(self) -> None:
        """Rotate to the next session and reset usage count."""
        self._current_index = (self._current_index + 1) % len(self._sessions)
        self._usage_count = 0

    @property
    def has_sessions(self) -> bool:
        """Check if any sessions are available."""
        return len(self._sessions) > 0

    @property
    def current_session_name(self) -> Optional[str]:
        """Name of current session for logging."""
        if not self._sessions:
            return None
        return self._session_names[self._current_index]
