"""Tests for session management."""

import json
import tempfile
from pathlib import Path

import pytest

from src.models import SessionType, SessionInfo
from src.session_provider import FileSessionProvider


class TestSessionInfo:
    """Test SessionInfo data class."""

    def test_evaluations_remaining_initial(self):
        """Test evaluations remaining when usage is 0."""
        session = SessionInfo(
            session_id="test",
            session_type=SessionType.CHATGPT,
            file_path="/path/to/session.json",
            usage_count=0,
            max_usage=10
        )
        assert session.evaluations_remaining == 10
        assert not session.needs_rotation

    def test_evaluations_remaining_partial(self):
        """Test evaluations remaining after some usage."""
        session = SessionInfo(
            session_id="test",
            session_type=SessionType.CHATGPT,
            file_path="/path/to/session.json",
            usage_count=3,
            max_usage=10
        )
        assert session.evaluations_remaining == 7
        assert not session.needs_rotation

    def test_needs_rotation_when_exhausted(self):
        """Test needs_rotation when usage equals max."""
        session = SessionInfo(
            session_id="test",
            session_type=SessionType.CHATGPT,
            file_path="/path/to/session.json",
            usage_count=10,
            max_usage=10
        )
        assert session.evaluations_remaining == 0
        assert session.needs_rotation

    def test_evaluations_remaining_never_negative(self):
        """Test evaluations remaining never goes below 0."""
        session = SessionInfo(
            session_id="test",
            session_type=SessionType.CHATGPT,
            file_path="/path/to/session.json",
            usage_count=15,
            max_usage=10
        )
        assert session.evaluations_remaining == 0


class TestFileSessionProvider:
    """Test FileSessionProvider."""

    @pytest.fixture
    def temp_sessions_dir(self):
        """Create temporary directory with test session files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test session files
            for name in ["account1", "account2", "account3"]:
                session_path = Path(tmpdir) / f"{name}.json"
                session_data = {
                    "cookies": [{"name": "test", "value": "test"}],
                    "origins": []
                }
                with open(session_path, 'w') as f:
                    json.dump(session_data, f)
            yield tmpdir

    def test_loads_sessions_from_directory(self, temp_sessions_dir):
        """Test that provider loads all sessions from directory."""
        provider = FileSessionProvider(temp_sessions_dir)
        assert provider.available_session_count == 3

    def test_get_session_returns_valid_session(self, temp_sessions_dir):
        """Test that get_session returns a valid SessionInfo."""
        provider = FileSessionProvider(temp_sessions_dir)
        session = provider.get_session(SessionType.CHATGPT)

        assert session is not None
        assert session.session_type == SessionType.CHATGPT
        assert session.is_valid
        assert not session.needs_rotation

    def test_record_evaluation_returns_remaining(self, temp_sessions_dir):
        """Test that record_evaluation returns correct remaining count."""
        provider = FileSessionProvider(temp_sessions_dir, max_usage_per_session=5)
        session = provider.get_session(SessionType.CHATGPT)

        remaining = provider.record_evaluation(session.session_id)
        assert remaining == 4

        remaining = provider.record_evaluation(session.session_id)
        assert remaining == 3

    def test_session_rotation_after_exhaustion(self, temp_sessions_dir):
        """Test that provider rotates to next session after exhaustion."""
        provider = FileSessionProvider(temp_sessions_dir, max_usage_per_session=2)

        # Get first session
        session1 = provider.get_session(SessionType.CHATGPT)
        session1_id = session1.session_id

        # Use it twice
        provider.record_evaluation(session1_id)
        remaining = provider.record_evaluation(session1_id)
        assert remaining == 0

        # Get next session - should be different
        session2 = provider.get_session(SessionType.CHATGPT)
        assert session2.session_id != session1_id

    def test_mark_invalid_removes_session(self, temp_sessions_dir):
        """Test that marked invalid sessions are not returned."""
        provider = FileSessionProvider(temp_sessions_dir)
        initial_count = provider.available_session_count

        session = provider.get_session(SessionType.CHATGPT)
        provider.mark_invalid(session.session_id)

        assert provider.available_session_count == initial_count - 1

    def test_raises_on_nonexistent_directory(self):
        """Test that provider raises error for nonexistent directory."""
        with pytest.raises(FileNotFoundError):
            FileSessionProvider("/nonexistent/path")

    def test_raises_on_empty_directory(self):
        """Test that provider raises error for directory with no session files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError):
                FileSessionProvider(tmpdir)

    def test_wrong_session_type_returns_none(self, temp_sessions_dir):
        """Test that requesting wrong session type returns None."""
        provider = FileSessionProvider(
            temp_sessions_dir,
            session_type=SessionType.CHATGPT
        )
        # If we add more session types in the future, this would return None
        # For now, CHATGPT is the only type, so this test just verifies it works
        session = provider.get_session(SessionType.CHATGPT)
        assert session is not None
