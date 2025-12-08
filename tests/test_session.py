"""Tests for session management."""

from src.session_provider import FileSessionProvider


class TestFileSessionProvider:
    """Test FileSessionProvider with real session file."""

    def test_loads_session_from_resources(self):
        """Test loading session from resources/sessions/llmheroai.json."""
        provider = FileSessionProvider("resources/sessions", max_usage_per_session=10)

        # Verify session is available
        assert provider.has_sessions

        # Verify get_session returns a valid StorageState dict
        storage_state = provider.get_session()
        assert storage_state is not None
        assert isinstance(storage_state, dict)
        assert "cookies" in storage_state
        assert "origins" in storage_state

        # Verify current_session_name
        assert provider.current_session_name == "llmheroai"

        # Verify record_evaluation returns EvaluationRecorded with correct values
        result = provider.record_evaluation()
        assert result.remaining == 9
        assert result.rotated == False
