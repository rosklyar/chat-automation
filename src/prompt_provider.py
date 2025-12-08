"""Prompt provider abstraction for sourcing prompts from various sources."""

import csv
import logging
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from .models import Prompt

logger = logging.getLogger(__name__)


class PromptParseError(Exception):
    """Raised when prompt source data is malformed or invalid."""
    pass


@runtime_checkable
class PromptProvider(Protocol):
    """
    Protocol for providing prompts from various sources.

    Implementations can source prompts from CSV files, Kafka streams,
    databases, or any other source.
    """

    def poll(self) -> Optional[Prompt]:
        """
        Get the next prompt from the source.

        Returns:
            Next prompt if available, None if source is exhausted.
        """
        ...

    @property
    def is_exhausted(self) -> bool:
        """
        Check if the source has no more prompts available.

        Returns:
            True if no more prompts can be provided, False otherwise.
        """
        ...

    def close(self) -> None:
        """Release any resources (files, connections, etc.)."""
        ...

    def __enter__(self) -> "PromptProvider":
        """Context manager entry."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        ...


class CsvPromptProvider:
    """
    Provides prompts by reading from a CSV file.

    Supports two modes:
    - Batch mode (default): Load all rows, return None when exhausted
    - Watch mode: Monitor file for new appends (tail -f style)

    The CSV file must have columns: id, prompt
    """

    def __init__(
        self,
        csv_path: str | Path,
        watch_for_changes: bool = False,
        poll_interval_seconds: float = 1.0
    ) -> None:
        """
        Initialize the CSV prompt provider.

        Args:
            csv_path: Path to CSV file with columns: id, prompt
            watch_for_changes: If True, monitor file for new rows (continuous mode)
            poll_interval_seconds: How often to check for new rows when watching

        Raises:
            FileNotFoundError: If CSV file does not exist.
            PromptParseError: If CSV is malformed or missing required columns.
        """
        self._csv_path = Path(csv_path)
        self._watch_for_changes = watch_for_changes
        self._poll_interval = poll_interval_seconds
        self._prompts: list[Prompt] = []
        self._current_index = 0
        self._file_size = 0  # Track file size to detect appends
        self._load_prompts()

    def _load_prompts(self) -> None:
        """Load all prompts from CSV file (initial load)."""
        if not self._csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {self._csv_path}")

        try:
            stat = self._csv_path.stat()
            self._file_size = stat.st_size

            with open(self._csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                # Validate required columns
                if reader.fieldnames is None:
                    raise PromptParseError(f"CSV file is empty: {self._csv_path}")

                if 'id' not in reader.fieldnames or 'prompt' not in reader.fieldnames:
                    raise PromptParseError(
                        f"CSV must have 'id' and 'prompt' columns. "
                        f"Found: {reader.fieldnames}"
                    )

                # Load all prompts
                for row_num, row in enumerate(reader, start=2):  # Start at 2 (1 is header)
                    try:
                        self._prompts.append(Prompt(id=row['id'], text=row['prompt']))
                    except KeyError as e:
                        raise PromptParseError(
                            f"Missing column in row {row_num}: {e}"
                        )

            logger.info(f"Loaded {len(self._prompts)} prompts from {self._csv_path}")

        except csv.Error as e:
            raise PromptParseError(f"Error parsing CSV file: {e}")

    def _check_for_new_rows(self) -> None:
        """Check if file has grown and load new rows (watch mode only)."""
        if not self._watch_for_changes:
            return

        try:
            stat = self._csv_path.stat()
            current_size = stat.st_size

            # File hasn't grown
            if current_size <= self._file_size:
                return

            # File grew - read new rows
            with open(self._csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                # Skip rows we've already read
                existing_count = len(self._prompts)
                for i, row in enumerate(reader):
                    if i < existing_count:
                        continue

                    # New row found
                    try:
                        prompt = Prompt(id=row['id'], text=row['prompt'])
                        self._prompts.append(prompt)
                        logger.info(f"Detected new prompt in CSV: {prompt.id}")
                    except KeyError as e:
                        logger.warning(f"Skipping malformed new row: {e}")

            self._file_size = current_size

        except (FileNotFoundError, IOError) as e:
            logger.warning(f"Error checking for new rows: {e}")

    def poll(self) -> Optional[Prompt]:
        """
        Get the next prompt from CSV.

        In watch mode, returns None temporarily if no more rows,
        but future calls may return data if file is appended to.

        Returns:
            Next prompt if available, None if no data currently available.
        """
        # Check for new appends if in watch mode
        if self._watch_for_changes:
            self._check_for_new_rows()

        # Return next prompt if available
        if self._current_index < len(self._prompts):
            prompt = self._prompts[self._current_index]
            self._current_index += 1
            return prompt

        # No more prompts
        return None

    @property
    def is_exhausted(self) -> bool:
        """
        Check if all prompts have been consumed.

        Returns:
            True if no more prompts available, False otherwise.
        """
        return self._current_index >= len(self._prompts)

    @property
    def total_count(self) -> int:
        """Get total number of prompts loaded from CSV."""
        return len(self._prompts)

    @property
    def remaining_count(self) -> int:
        """Get number of prompts not yet consumed."""
        return max(0, len(self._prompts) - self._current_index)

    def close(self) -> None:
        """Release resources (no-op for CSV provider)."""
        pass

    def __enter__(self) -> "CsvPromptProvider":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup resources."""
        self.close()
