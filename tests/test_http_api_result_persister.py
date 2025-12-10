"""Tests for HTTP API result persister."""

import json
import pytest
import responses
from datetime import datetime
from requests.exceptions import Timeout, ConnectionError

from src.models import Prompt, EvaluationResult, Citation
from src.result_persister import HttpApiResultPersister, PersistenceError


class TestHttpApiResultPersister:
    """Tests for HttpApiResultPersister implementation."""

    @pytest.fixture
    def base_url(self) -> str:
        """Base URL for mock API."""
        return "https://api.example.com"

    @pytest.fixture
    def submit_url(self, base_url: str) -> str:
        """Submit endpoint URL."""
        return f"{base_url}/evaluations/api/v1/submit"

    @pytest.fixture
    def release_url(self, base_url: str) -> str:
        """Release endpoint URL."""
        return f"{base_url}/evaluations/api/v1/release"

    def test_initialization_success(self, base_url: str):
        """Test successful initialization with valid parameters."""
        persister = HttpApiResultPersister(
            api_base_url=base_url,
            submit_retry_attempts=3
        )
        assert persister._submit_endpoint == f"{base_url}/evaluations/api/v1/submit"
        assert persister._release_endpoint == f"{base_url}/evaluations/api/v1/release"
        assert persister._submit_retry_attempts == 3

    def test_initialization_removes_trailing_slash(self):
        """Test that trailing slash is removed from base URL."""
        persister = HttpApiResultPersister(
            api_base_url="https://api.example.com/"
        )
        assert persister._api_base_url == "https://api.example.com"
        assert persister._submit_endpoint == "https://api.example.com/evaluations/api/v1/submit"

    def test_initialization_with_empty_url(self):
        """Test initialization fails with empty URL."""
        with pytest.raises(ValueError, match="cannot be empty"):
            HttpApiResultPersister(api_base_url="")

    @responses.activate
    def test_submit_answer_success(self, base_url: str, submit_url: str):
        """Test successful answer submission."""
        responses.post(
            submit_url,
            json={
                "evaluation_id": 123,
                "prompt_id": 456,
                "status": "completed",
                "completed_at": "2025-12-09T10:35:00Z"
            },
            status=200
        )

        persister = HttpApiResultPersister(base_url)
        prompt = Prompt(
            id="456",
            text="What is Python?",
            evaluation_id=123
        )
        result = EvaluationResult(
            response_text="Python is a programming language",
            citations=[Citation(url="https://python.org", text="Python Docs")],
            timestamp=datetime(2025, 12, 9, 10, 35, 0),
            success=True
        )

        persister.save(prompt, result, run_number=1)

        # Verify request
        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["evaluation_id"] == 123
        assert "answer" in request_body
        assert request_body["answer"]["response"] == "Python is a programming language"
        assert len(request_body["answer"]["citations"]) == 1
        assert request_body["answer"]["citations"][0]["url"] == "https://python.org"
        assert "timestamp" in request_body["answer"]

    @responses.activate
    def test_release_evaluation_on_failure(self, base_url: str, release_url: str):
        """Test release evaluation when run_number is 0."""
        responses.post(
            release_url,
            json={
                "evaluation_id": 123,
                "action": "marked_failed"
            },
            status=200
        )

        persister = HttpApiResultPersister(base_url)
        prompt = Prompt(
            id="456",
            text="What is Python?",
            evaluation_id=123
        )
        result = EvaluationResult(
            response_text="",
            citations=[],
            success=False,
            error_message="No citations found after 3 attempts"
        )

        persister.save(prompt, result, run_number=0)

        # Verify request
        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["evaluation_id"] == 123
        assert request_body["mark_as_failed"] is True
        assert request_body["failure_reason"] == "No citations found after 3 attempts"

    def test_skip_when_missing_evaluation_id(self, base_url: str, caplog):
        """Test that save skips API call when evaluation_id is missing."""
        persister = HttpApiResultPersister(base_url)
        prompt = Prompt(id="1", text="test")  # No evaluation_id
        result = EvaluationResult(
            response_text="answer",
            citations=[],
            success=True
        )

        # Should not raise error
        persister.save(prompt, result, run_number=1)

        # Should log warning
        assert "missing evaluation_id" in caplog.text
        assert "Skipping API submission" in caplog.text

    @responses.activate
    def test_submit_retries_on_500_error(self, base_url: str, submit_url: str):
        """Test that submit retries on 5xx server errors."""
        # First two attempts: 500 error
        responses.post(submit_url, status=500)
        responses.post(submit_url, status=500)
        # Third attempt: success
        responses.post(
            submit_url,
            json={"evaluation_id": 123, "status": "completed"},
            status=200
        )

        persister = HttpApiResultPersister(
            base_url,
            submit_retry_attempts=3,
            retry_delay_seconds=0.1
        )
        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="answer",
            citations=[],
            success=True
        )

        persister.save(prompt, result, run_number=1)

        # Should have made 3 requests
        assert len(responses.calls) == 3

    @responses.activate
    def test_submit_does_not_retry_on_400_error(self, base_url: str, submit_url: str):
        """Test that submit does not retry on 4xx client errors."""
        responses.post(submit_url, status=400)

        persister = HttpApiResultPersister(
            base_url,
            submit_retry_attempts=3
        )
        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="answer",
            citations=[],
            success=True
        )

        with pytest.raises(PersistenceError, match="rejected"):
            persister.save(prompt, result, run_number=1)

        # Should only make one request (no retries)
        assert len(responses.calls) == 1

    @responses.activate
    def test_submit_fails_after_max_retries(self, base_url: str, submit_url: str):
        """Test that submit raises error after max retries exhausted."""
        responses.post(submit_url, status=500)
        responses.post(submit_url, status=500)
        responses.post(submit_url, status=500)

        persister = HttpApiResultPersister(
            base_url,
            submit_retry_attempts=3,
            retry_delay_seconds=0.1
        )
        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="answer",
            citations=[],
            success=True
        )

        with pytest.raises(PersistenceError, match="server error"):
            persister.save(prompt, result, run_number=1)

    @responses.activate
    def test_submit_handles_timeout(self, base_url: str, submit_url: str):
        """Test that submit handles timeout errors."""
        responses.post(submit_url, body=Timeout())

        persister = HttpApiResultPersister(
            base_url,
            submit_retry_attempts=1
        )
        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="answer",
            citations=[],
            success=True
        )

        with pytest.raises(PersistenceError, match="timed out"):
            persister.save(prompt, result, run_number=1)

    @responses.activate
    def test_submit_handles_malformed_json(self, base_url: str, submit_url: str):
        """Test that submit handles malformed JSON response."""
        responses.post(submit_url, body="not json", status=200)

        persister = HttpApiResultPersister(base_url)
        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="answer",
            citations=[],
            success=True
        )

        with pytest.raises(PersistenceError, match="malformed response"):
            persister.save(prompt, result, run_number=1)

    @responses.activate
    def test_release_with_default_failure_reason(self, base_url: str, release_url: str):
        """Test release uses default failure reason if error_message is missing."""
        responses.post(
            release_url,
            json={"evaluation_id": 123, "action": "marked_failed"},
            status=200
        )

        persister = HttpApiResultPersister(base_url)
        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="",
            citations=[],
            success=False
            # No error_message
        )

        persister.save(prompt, result, run_number=0)

        # Verify default reason used
        request_body = json.loads(responses.calls[0].request.body)
        assert "failure_reason" in request_body
        assert "failed without specific reason" in request_body["failure_reason"]

    @responses.activate
    def test_release_does_not_raise_on_timeout(self, base_url: str, release_url: str, caplog):
        """Test that release does not raise error on timeout (best-effort)."""
        responses.post(release_url, body=Timeout())

        persister = HttpApiResultPersister(base_url)
        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="",
            citations=[],
            success=False,
            error_message="Test failure"
        )

        # Should not raise
        persister.save(prompt, result, run_number=0)

        # Should log warning (may be logged as "Release timeout" or "Release network error")
        assert "non-critical" in caplog.text
        assert "evaluation_id=123" in caplog.text

    def test_output_location_property(self, base_url: str):
        """Test output_location returns base URL."""
        persister = HttpApiResultPersister(base_url)
        assert persister.output_location == base_url

    @responses.activate
    def test_context_manager(self, base_url: str, submit_url: str):
        """Test persister works as context manager."""
        responses.post(
            submit_url,
            json={"evaluation_id": 123, "status": "completed"},
            status=200
        )

        with HttpApiResultPersister(base_url) as persister:
            prompt = Prompt(id="1", text="test", evaluation_id=123)
            result = EvaluationResult(
                response_text="answer",
                citations=[],
                success=True
            )
            persister.save(prompt, result, run_number=1)

    def test_close_method(self, base_url: str):
        """Test close method releases resources."""
        persister = HttpApiResultPersister(base_url)
        persister.close()

        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="answer",
            citations=[],
            success=True
        )

        # Should not be able to save after close
        with pytest.raises(PersistenceError, match="closed"):
            persister.save(prompt, result, run_number=1)

    def test_close_idempotent(self, base_url: str):
        """Test close can be called multiple times safely."""
        persister = HttpApiResultPersister(base_url)
        persister.close()
        persister.close()  # Should not raise

    @responses.activate
    def test_multiple_citations_serialized(self, base_url: str, submit_url: str):
        """Test that multiple citations are properly serialized."""
        responses.post(
            submit_url,
            json={"evaluation_id": 123, "status": "completed"},
            status=200
        )

        persister = HttpApiResultPersister(base_url)
        prompt = Prompt(id="1", text="test", evaluation_id=123)
        result = EvaluationResult(
            response_text="answer",
            citations=[
                Citation(url="https://example1.com", text="Source 1"),
                Citation(url="https://example2.com", text="Source 2"),
                Citation(url="https://example3.com", text="Source 3")
            ],
            success=True
        )

        persister.save(prompt, result, run_number=1)

        request_body = json.loads(responses.calls[0].request.body)
        assert len(request_body["answer"]["citations"]) == 3
        assert request_body["answer"]["citations"][0]["url"] == "https://example1.com"
        assert request_body["answer"]["citations"][1]["text"] == "Source 2"
