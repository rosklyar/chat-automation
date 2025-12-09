"""Result persistence protocol and implementations."""

import json
import logging
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

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


class JsonResultPersister:
    """
    Persists evaluation results to a JSON file.

    Output format groups results by prompt:
    [
        {
            "prompt_id": "1",
            "prompt": "...",
            "answers": [
                {
                    "run_number": 1,
                    "response": "...",
                    "citations": [{"url": "...", "text": "..."}],
                    "timestamp": "...",
                    "success": true,
                    "error_message": null
                }
            ]
        }
    ]

    Features:
    - Loads existing file on init for resume capability
    - Writes eagerly after each save() for durability
    - Groups multiple results under same prompt
    """

    def __init__(self, output_path: str | Path) -> None:
        """
        Initialize the JSON result persister.

        Args:
            output_path: Path to output JSON file. Created if doesn't exist.
                        Existing data is loaded for resume capability.
        """
        self._output_path = Path(output_path)
        self._data: list[dict] = self._load_existing()
        self._closed = False

    def _load_existing(self) -> list[dict]:
        """Load existing results if file exists (resume capability)."""
        if self._output_path.exists():
            try:
                with open(self._output_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} existing entries from {self._output_path}")
                    return data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load existing file: {e}")
                return []
        return []

    def _find_or_create_entry(self, prompt: Prompt) -> dict:
        """Find existing prompt entry or create new one."""
        for entry in self._data:
            if entry.get('prompt_id') == prompt.id:
                return entry

        entry = {
            'prompt_id': prompt.id,
            'prompt': prompt.text,
            'answers': [],
        }
        self._data.append(entry)
        return entry

    def _write_to_disk(self) -> None:
        """Write data to file (eager persistence)."""
        try:
            # Ensure parent directory exists
            self._output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self._output_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            raise PersistenceError(f"Failed to write to {self._output_path}", cause=e)

    def save(
        self,
        prompt: Prompt,
        result: EvaluationResult,
        run_number: int
    ) -> None:
        """
        Persist an evaluation result to JSON file.

        Empty results (run_number=0) create the prompt entry with empty answers.
        Non-empty results are appended to the prompt's answers array.
        """
        if self._closed:
            raise PersistenceError("Cannot save to closed persister")

        entry = self._find_or_create_entry(prompt)

        # Only add to answers if this is a real result (run_number > 0)
        if run_number > 0:
            answer = {
                'run_number': run_number,
                'response': result.response_text,
                'citations': [c.to_dict() for c in result.citations],
                'timestamp': result.timestamp.isoformat(),
                'success': result.success,
            }
            # Only include error_message if present
            if result.error_message:
                answer['error_message'] = result.error_message

            # Include API metadata if present (from HttpApiPromptProvider)
            if prompt.evaluation_id is not None:
                answer['evaluation_id'] = prompt.evaluation_id
            if prompt.topic_id is not None:
                answer['topic_id'] = prompt.topic_id
            if prompt.claimed_at is not None:
                answer['claimed_at'] = prompt.claimed_at

            entry['answers'].append(answer)
        else:
            # Empty result - just ensure entry exists (already done above)
            logger.warning(f"Saving empty result for prompt {prompt.id}")

        self._write_to_disk()

    def close(self) -> None:
        """Release resources. Safe to call multiple times."""
        if not self._closed:
            self._closed = True
            logger.debug(f"Closed JSON persister for {self._output_path}")

    @property
    def output_location(self) -> str:
        """Return the output file path as string."""
        return str(self._output_path)

    def __enter__(self) -> "JsonResultPersister":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
