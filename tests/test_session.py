import json


class TestSessionValidation:
    """Test session file validation."""

    def test_session_file_structure(self):
        """Test that resources/sessions/llmheroai.json has correct structure."""
        session_file = "resources/sessions/llmheroai.json"

        with open(session_file, 'r') as f:
            data = json.load(f)

        assert 'cookies' in data, "Session file must contain 'cookies' key"
        assert 'origins' in data, "Session file must contain 'origins' key"
        assert isinstance(data['cookies'], list), "'cookies' must be an array"
        assert isinstance(data['origins'], list), "'origins' must be an array"
