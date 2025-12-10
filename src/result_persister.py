"""Result persistence protocol and implementations."""

import logging
import sys
import time
from typing import Optional, Protocol, runtime_checkable

import requests
from requests.exceptions import RequestException, Timeout, HTTPError

from .models import Prompt, EvaluationResult

logger = logging.getLogger(__name__)


class PersistenceError(Exception):
    """Raised when result persistence fails."""

    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        """
        Initialize persistence error.

        Args:
            message: Error description.
            cause: Original exception that caused this error (if any).
        """
        super().__init__(message)
        self.cause = cause


@runtime_checkable
class ResultPersister(Protocol):
    """
    Protocol for persisting evaluation results.

    Implementations can store results in various backends:
    - JSON files (with prompt grouping)
    - Databases (flat or normalized tables)
    - Remote APIs

    Results are persisted durably by the time close() or __exit__ completes.
    Implementations MAY write eagerly on each save() call, or batch writes.

    Usage:
        with JsonResultPersister("results.json") as persister:
            for prompt in prompts:
                result = bot.evaluate(prompt.text)
                persister.save(prompt, result, run_number=1)
    """

    def save(
        self,
        prompt: Prompt,
        result: EvaluationResult,
        run_number: int
    ) -> None:
        """
        Persist an evaluation result.

        Args:
            prompt: The prompt that was evaluated (id and text).
            result: The evaluation outcome (response, citations, status).
            run_number: Which attempt produced this result (1-indexed).
                       Use 0 to indicate "no successful attempts" (empty result).

        Raises:
            PersistenceError: If the result could not be saved.
        """
        ...

    def close(self) -> None:
        """
        Release resources and ensure all data is persisted.

        Safe to call multiple times. After close(), save() calls will raise.
        """
        ...

    @property
    def output_location(self) -> str:
        """
        Human-readable description of where results are stored.

        Used for logging (e.g., "results.json", "postgres://db/results", "api.example.com").
        """
        ...

    def __enter__(self) -> "ResultPersister":
        """Context manager entry."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - ensures close() is called."""
        ...


class HttpApiResultPersister:
    """
    Persists evaluation results by submitting to HTTP API endpoints.

    Successful evaluations are submitted to POST /evaluations/api/v1/submit.
    Failed evaluations are released via POST /evaluations/api/v1/release.

    For API-based workflows where prompts are claimed atomically from an
    evaluation service, this persister completes the loop by reporting results
    back to the service.
    """

    def __init__(
        self,
        api_base_url: str,
        submit_retry_attempts: int = 3,
        timeout_seconds: float = 30.0,
        retry_delay_seconds: float = 1.0
    ) -> None:
        """
        Initialize HTTP API result persister.

        Args:
            api_base_url: Base API URL (e.g., "http://localhost:8000")
            submit_retry_attempts: Max retry attempts for submit endpoint
            timeout_seconds: Request timeout in seconds
            retry_delay_seconds: Delay between retries

        Raises:
            ValueError: If api_base_url is invalid or empty
        """
        # Validate inputs
        if not api_base_url or not api_base_url.strip():
            raise ValueError("api_base_url cannot be empty")

        # Normalize URL (remove trailing slash)
        self._api_base_url = api_base_url.rstrip('/')
        self._submit_endpoint = f"{self._api_base_url}/evaluations/api/v1/submit"
        self._release_endpoint = f"{self._api_base_url}/evaluations/api/v1/release"

        self._submit_retry_attempts = submit_retry_attempts
        self._timeout = timeout_seconds
        self._retry_delay = retry_delay_seconds

        # Create persistent session for connection pooling
        self._session = requests.Session()
        self._session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

        self._closed = False

        logger.info(
            f"Initialized HTTP API result persister: {self._api_base_url} "
            f"(submit_retries={submit_retry_attempts})"
        )

    def save(
        self,
        prompt: Prompt,
        result: EvaluationResult,
        run_number: int
    ) -> None:
        """
        Persist evaluation result to API.

        For successful evaluations (run_number > 0), submits answer to API.
        For failed evaluations (run_number == 0), releases evaluation as failed.

        If prompt is missing evaluation_id (e.g., from CSV provider),
        logs warning and skips API submission.

        Args:
            prompt: The prompt that was evaluated
            result: The evaluation outcome
            run_number: Which attempt produced this result (0 = failure)

        Raises:
            PersistenceError: If API submission fails persistently
        """
        if self._closed:
            raise PersistenceError("Cannot save to closed persister")

        # Check if prompt has evaluation_id (required for API submission)
        if prompt.evaluation_id is None:
            logger.warning(
                f"Skipping API submission for prompt {prompt.id}: "
                f"missing evaluation_id (prompt source may be CSV)"
            )
            return

        try:
            if run_number > 0:
                # Success case: submit answer
                self._submit_answer(prompt, result)
                logger.info(
                    f"Submitted answer for evaluation_id={prompt.evaluation_id}, "
                    f"prompt_id={prompt.id}"
                )
            else:
                # Failure case: release evaluation
                self._release_evaluation(prompt, result)
                logger.info(
                    f"Released failed evaluation_id={prompt.evaluation_id}, "
                    f"prompt_id={prompt.id}"
                )
        except PersistenceError:
            # Re-raise our own errors
            raise
        except Exception as e:
            # Wrap unexpected errors
            raise PersistenceError(
                f"Unexpected error persisting result for evaluation_id={prompt.evaluation_id}",
                cause=e
            )

    def _submit_answer(self, prompt: Prompt, result: EvaluationResult) -> None:
        """
        Submit successful evaluation to /evaluations/api/v1/submit.

        Retries on transient failures (timeouts, 5xx errors, network errors).
        Does not retry on 4xx client errors.

        Args:
            prompt: The prompt with evaluation_id
            result: The successful evaluation result

        Raises:
            PersistenceError: If submission fails after retries
        """
        request_body = {
            "evaluation_id": prompt.evaluation_id,
            "answer": {
                "response": result.response_text,
                "citations": [c.to_dict() for c in result.citations],
                "timestamp": result.timestamp.isoformat()
            }
        }

        # Retry logic for transient failures
        for attempt in range(1, self._submit_retry_attempts + 1):
            try:
                response = self._session.post(
                    self._submit_endpoint,
                    json=request_body,
                    timeout=self._timeout
                )

                # Check HTTP status
                response.raise_for_status()

                # Parse response - catch JSON errors
                try:
                    data = response.json()
                except ValueError as e:
                    logger.error(f"Invalid API response format (invalid JSON): {e}")
                    raise PersistenceError(
                        f"API returned malformed response: {e}",
                        cause=e
                    )

                logger.debug(
                    f"Submit successful: evaluation_id={data.get('evaluation_id')}, "
                    f"status={data.get('status')}"
                )
                return

            except PersistenceError:
                # Re-raise our own errors
                raise

            except Timeout:
                logger.warning(
                    f"Submit timeout (attempt {attempt}/{self._submit_retry_attempts}): "
                    f"evaluation_id={prompt.evaluation_id}"
                )
                if attempt < self._submit_retry_attempts:
                    time.sleep(self._retry_delay)
                    continue
                raise PersistenceError(
                    f"Submit timed out after {self._submit_retry_attempts} attempts",
                    cause=sys.exc_info()[1]
                )

            except HTTPError as e:
                # 4xx/5xx errors
                status_code = e.response.status_code if hasattr(e, 'response') and e.response else None

                # If we can't get status code from exception, try to parse from message
                if status_code is None and hasattr(e, 'args') and e.args:
                    try:
                        msg = str(e.args[0])
                        if msg and msg[0:3].isdigit():
                            status_code = int(msg[0:3])
                    except (ValueError, IndexError):
                        pass

                logger.error(
                    f"Submit HTTP error {status_code}: {e}"
                )

                # Don't retry 4xx client errors
                if status_code and 400 <= status_code < 500:
                    raise PersistenceError(
                        f"API rejected submit request (HTTP {status_code})",
                        cause=e
                    )

                # Retry 5xx server errors
                if attempt < self._submit_retry_attempts:
                    logger.warning(f"Retrying submit after server error (attempt {attempt})")
                    time.sleep(self._retry_delay)
                    continue
                raise PersistenceError(
                    f"Submit failed with server error after {self._submit_retry_attempts} attempts",
                    cause=e
                )

            except RequestException as e:
                # Network errors, connection errors
                logger.warning(
                    f"Submit network error (attempt {attempt}/{self._submit_retry_attempts}): {e}"
                )
                if attempt < self._submit_retry_attempts:
                    time.sleep(self._retry_delay)
                    continue
                raise PersistenceError(
                    f"Submit failed with network error after {self._submit_retry_attempts} attempts",
                    cause=e
                )

    def _release_evaluation(self, prompt: Prompt, result: EvaluationResult) -> None:
        """
        Release failed evaluation to /evaluations/api/v1/release.

        Always uses mark_as_failed=true to preserve evaluation for analytics.
        Does not retry - this is best-effort cleanup.

        Args:
            prompt: The prompt with evaluation_id
            result: The failed evaluation result (should have error_message)

        Raises:
            PersistenceError: If release fails
        """
        # Get failure reason from result's error_message, or use default
        failure_reason = result.error_message or "Evaluation failed without specific reason"

        request_body = {
            "evaluation_id": prompt.evaluation_id,
            "mark_as_failed": True,
            "failure_reason": failure_reason
        }

        try:
            response = self._session.post(
                self._release_endpoint,
                json=request_body,
                timeout=self._timeout
            )

            # Check HTTP status
            response.raise_for_status()

            # Parse response
            try:
                data = response.json()
            except ValueError as e:
                logger.warning(f"Release response malformed (non-critical): {e}")
                return  # Best-effort - don't fail

            logger.debug(
                f"Release successful: evaluation_id={data.get('evaluation_id')}, "
                f"action={data.get('action')}"
            )

        except Timeout as e:
            # Best-effort - log but don't fail
            logger.warning(
                f"Release timeout for evaluation_id={prompt.evaluation_id} "
                f"(non-critical): {e}"
            )

        except HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') and e.response else None
            logger.warning(
                f"Release HTTP error {status_code} for evaluation_id={prompt.evaluation_id} "
                f"(non-critical): {e}"
            )

        except RequestException as e:
            logger.warning(
                f"Release network error for evaluation_id={prompt.evaluation_id} "
                f"(non-critical): {e}"
            )

    def close(self) -> None:
        """
        Release HTTP session resources.

        Safe to call multiple times. After close(), save() will raise.
        """
        if not self._closed:
            self._session.close()
            self._closed = True
            logger.debug("Closed HTTP API result persister session")

    @property
    def output_location(self) -> str:
        """Return the API base URL as string."""
        return self._api_base_url

    def __enter__(self) -> "HttpApiResultPersister":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup resources."""
        self.close()


__all__ = [
    'ResultPersister',
    'HttpApiResultPersister',
    'PersistenceError'
]
