import json
import os
import tempfile


class TestSessionValidation:
    """Test session file validation."""

    def test_valid_session_file_structure(self):
        """Test that a valid session file has correct JSON structure."""
        # Create a temporary valid session file
        session_data = {
            "cookies": [
                {
                    "name": "test_cookie",
                    "value": "test_value",
                    "domain": "chatgpt.com",
                    "path": "/"
                }
            ],
            "origins": []
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(session_data, f)
            temp_file = f.name

        try:
            # Read and validate
            with open(temp_file, 'r') as f:
                data = json.load(f)

            assert 'cookies' in data
            assert 'origins' in data
            assert isinstance(data['cookies'], list)
            assert isinstance(data['origins'], list)
        finally:
            os.unlink(temp_file)
