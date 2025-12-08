"""Tests for result persister abstraction."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.models import Prompt, EvaluationResult, Citation
from src.result_persister import JsonResultPersister, PersistenceError


class TestJsonResultPersister:
    """Tests for JsonResultPersister implementation."""

    @pytest.fixture
    def tmp_output(self, tmp_path: Path) -> Path:
        """Create temporary output path."""
        return tmp_path / "results.json"

    def test_initialization_creates_new_file_on_first_save(self, tmp_output: Path):
        """Test that new file is created on first save."""
        persister = JsonResultPersister(tmp_output)
        assert not tmp_output.exists()  # Not created until first save

        prompt = Prompt(id="1", text="test prompt")
        result = EvaluationResult(response_text="response")

        persister.save(prompt, result, run_number=1)

        assert tmp_output.exists()

    def test_loads_existing_file_on_init(self, tmp_output: Path):
        """Test that existing file is loaded for resume capability."""
        # Create existing file
        existing_data = [
            {
                "prompt_id": "1",
                "prompt": "existing prompt",
                "answers": [
                    {
                        "run_number": 1,
                        "response": "existing response",
                        "citations": [],
                        "timestamp": "2025-01-01T00:00:00",
                        "success": True
                    }
                ]
            }
        ]
        tmp_output.write_text(json.dumps(existing_data))

        # Initialize persister and add new result
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="2", text="new prompt")
        persister.save(prompt, EvaluationResult(response_text="new response"), run_number=1)

        # Verify both entries exist
        data = json.loads(tmp_output.read_text())
        assert len(data) == 2
        assert data[0]["prompt_id"] == "1"
        assert data[1]["prompt_id"] == "2"

    def test_save_groups_by_prompt(self, tmp_output: Path):
        """Test that multiple results for same prompt are grouped."""
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="1", text="test")

        persister.save(prompt, EvaluationResult(response_text="r1"), run_number=1)
        persister.save(prompt, EvaluationResult(response_text="r2"), run_number=2)
        persister.save(prompt, EvaluationResult(response_text="r3"), run_number=3)

        data = json.loads(tmp_output.read_text())

        assert len(data) == 1  # Only one prompt entry
        assert len(data[0]["answers"]) == 3  # Three answers
        assert data[0]["answers"][0]["response"] == "r1"
        assert data[0]["answers"][1]["response"] == "r2"
        assert data[0]["answers"][2]["response"] == "r3"

    def test_save_empty_result(self, tmp_output: Path):
        """Test saving empty result (run_number=0)."""
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="1", text="test")
        empty_result = EvaluationResult(response_text="", citations=[], success=False)

        persister.save(prompt, empty_result, run_number=0)

        data = json.loads(tmp_output.read_text())

        assert len(data) == 1
        assert data[0]["prompt_id"] == "1"
        assert data[0]["prompt"] == "test"
        assert data[0]["answers"] == []  # Empty answers array

    def test_save_includes_citations(self, tmp_output: Path):
        """Test that citations are properly serialized."""
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="1", text="test")

        citations = [
            Citation(url="https://example.com/1", text="Source 1", number=1),
            Citation(url="https://example.com/2", text="Source 2", number=2),
        ]
        result = EvaluationResult(response_text="response", citations=citations)

        persister.save(prompt, result, run_number=1)

        data = json.loads(tmp_output.read_text())
        answer = data[0]["answers"][0]

        assert len(answer["citations"]) == 2
        assert answer["citations"][0]["url"] == "https://example.com/1"
        assert answer["citations"][0]["text"] == "Source 1"
        assert answer["citations"][1]["url"] == "https://example.com/2"
        assert answer["citations"][1]["text"] == "Source 2"

    def test_save_includes_success_field(self, tmp_output: Path):
        """Test that success field is persisted."""
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="1", text="test")

        # Successful result
        result_success = EvaluationResult(response_text="ok", success=True)
        persister.save(prompt, result_success, run_number=1)

        # Failed result
        result_fail = EvaluationResult(response_text="fail", success=False)
        persister.save(prompt, result_fail, run_number=2)

        data = json.loads(tmp_output.read_text())
        answers = data[0]["answers"]

        assert answers[0]["success"] is True
        assert answers[1]["success"] is False

    def test_save_includes_error_message(self, tmp_output: Path):
        """Test that error_message is persisted when present."""
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="1", text="test")

        result_with_error = EvaluationResult(
            response_text="",
            success=False,
            error_message="Rate limited"
        )
        persister.save(prompt, result_with_error, run_number=1)

        data = json.loads(tmp_output.read_text())
        answer = data[0]["answers"][0]

        assert answer["error_message"] == "Rate limited"

    def test_save_omits_error_message_when_none(self, tmp_output: Path):
        """Test that error_message is omitted when None."""
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="1", text="test")

        result = EvaluationResult(response_text="ok", success=True, error_message=None)
        persister.save(prompt, result, run_number=1)

        data = json.loads(tmp_output.read_text())
        answer = data[0]["answers"][0]

        assert "error_message" not in answer

    def test_save_includes_timestamp(self, tmp_output: Path):
        """Test that timestamp is persisted."""
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="1", text="test")

        timestamp = datetime(2025, 1, 15, 12, 30, 45)
        result = EvaluationResult(response_text="response", timestamp=timestamp)

        persister.save(prompt, result, run_number=1)

        data = json.loads(tmp_output.read_text())
        answer = data[0]["answers"][0]

        assert answer["timestamp"] == "2025-01-15T12:30:45"

    def test_save_includes_run_number(self, tmp_output: Path):
        """Test that run_number is persisted."""
        persister = JsonResultPersister(tmp_output)
        prompt = Prompt(id="1", text="test")

        persister.save(prompt, EvaluationResult(response_text="r1"), run_number=1)
        persister.save(prompt, EvaluationResult(response_text="r2"), run_number=3)

        data = json.loads(tmp_output.read_text())
        answers = data[0]["answers"]

        assert answers[0]["run_number"] == 1
        assert answers[1]["run_number"] == 3

    def test_save_after_close_raises_error(self, tmp_output: Path):
        """Test that saving after close raises PersistenceError."""
        persister = JsonResultPersister(tmp_output)
        persister.close()

        prompt = Prompt(id="1", text="test")
        result = EvaluationResult(response_text="response")

        with pytest.raises(PersistenceError, match="Cannot save to closed persister"):
            persister.save(prompt, result, run_number=1)

    def test_close_is_idempotent(self, tmp_output: Path):
        """Test that close can be called multiple times safely."""
        persister = JsonResultPersister(tmp_output)

        persister.close()
        persister.close()  # Should not raise
        persister.close()  # Should not raise

    def test_context_manager(self, tmp_output: Path):
        """Test context manager usage."""
        prompt = Prompt(id="1", text="test")
        result = EvaluationResult(response_text="response")

        with JsonResultPersister(tmp_output) as persister:
            persister.save(prompt, result, run_number=1)

        # Verify file was written
        assert tmp_output.exists()

        # Verify persister is closed
        with pytest.raises(PersistenceError):
            persister.save(prompt, result, run_number=2)

    def test_output_location_property(self, tmp_output: Path):
        """Test output_location property returns path string."""
        persister = JsonResultPersister(tmp_output)

        location = persister.output_location

        assert isinstance(location, str)
        assert "results.json" in location

    def test_creates_parent_directory(self, tmp_path: Path):
        """Test that parent directories are created if missing."""
        nested_output = tmp_path / "nested" / "dir" / "results.json"
        persister = JsonResultPersister(nested_output)

        prompt = Prompt(id="1", text="test")
        result = EvaluationResult(response_text="response")

        persister.save(prompt, result, run_number=1)

        assert nested_output.exists()
        assert nested_output.parent.exists()

    def test_handles_unicode_content(self, tmp_output: Path):
        """Test handling of unicode characters in prompts and responses."""
        persister = JsonResultPersister(tmp_output)

        prompt = Prompt(id="1", text="日本語のプロンプト")
        result = EvaluationResult(response_text="Відповідь українською 🎉")

        persister.save(prompt, result, run_number=1)

        data = json.loads(tmp_output.read_text())

        assert data[0]["prompt"] == "日本語のプロンプト"
        assert data[0]["answers"][0]["response"] == "Відповідь українською 🎉"

    def test_multiple_prompts(self, tmp_output: Path):
        """Test saving results for multiple different prompts."""
        persister = JsonResultPersister(tmp_output)

        prompts = [
            Prompt(id="1", text="First"),
            Prompt(id="2", text="Second"),
            Prompt(id="3", text="Third"),
        ]

        for prompt in prompts:
            persister.save(prompt, EvaluationResult(response_text=f"Response for {prompt.id}"), run_number=1)

        data = json.loads(tmp_output.read_text())

        assert len(data) == 3
        assert data[0]["prompt_id"] == "1"
        assert data[1]["prompt_id"] == "2"
        assert data[2]["prompt_id"] == "3"

    def test_malformed_existing_file_is_ignored(self, tmp_output: Path):
        """Test that malformed existing file is ignored and new file created."""
        # Create malformed JSON
        tmp_output.write_text("{this is not valid json")

        # Should not raise, should just start fresh
        persister = JsonResultPersister(tmp_output)

        prompt = Prompt(id="1", text="test")
        persister.save(prompt, EvaluationResult(response_text="response"), run_number=1)

        # Verify new valid data was written
        data = json.loads(tmp_output.read_text())
        assert len(data) == 1
        assert data[0]["prompt_id"] == "1"

    def test_pathlib_path_support(self, tmp_path: Path):
        """Test that persister accepts both string and Path objects."""
        # Test with Path object
        persister1 = JsonResultPersister(tmp_path / "results1.json")
        assert persister1.output_location

        # Test with string
        persister2 = JsonResultPersister(str(tmp_path / "results2.json"))
        assert persister2.output_location
