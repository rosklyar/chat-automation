"""Tests for prompt provider abstraction."""

import csv
import tempfile
from pathlib import Path

import pytest

from src.models import Prompt
from src.prompt_provider import CsvPromptProvider, PromptParseError


class TestCsvPromptProvider:
    """Tests for CsvPromptProvider implementation."""

    @pytest.fixture
    def valid_csv(self, tmp_path: Path) -> Path:
        """Create a valid CSV file with test prompts."""
        csv_file = tmp_path / "prompts.csv"
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'prompt'])
            writer.writeheader()
            writer.writerow({'id': '1', 'prompt': 'What is Python?'})
            writer.writerow({'id': '2', 'prompt': 'Explain machine learning'})
            writer.writerow({'id': '3', 'prompt': 'What is a REST API?'})
        return csv_file

    @pytest.fixture
    def empty_csv(self, tmp_path: Path) -> Path:
        """Create an empty CSV file."""
        csv_file = tmp_path / "empty.csv"
        csv_file.touch()
        return csv_file

    @pytest.fixture
    def missing_columns_csv(self, tmp_path: Path) -> Path:
        """Create a CSV file with missing required columns."""
        csv_file = tmp_path / "bad.csv"
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'text'])
            writer.writeheader()
            writer.writerow({'id': '1', 'text': 'Some text'})
        return csv_file

    @pytest.fixture
    def header_only_csv(self, tmp_path: Path) -> Path:
        """Create a CSV file with only headers, no data."""
        csv_file = tmp_path / "header_only.csv"
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'prompt'])
            writer.writeheader()
        return csv_file

    def test_initialization_with_valid_csv(self, valid_csv: Path):
        """Test successful initialization with a valid CSV file."""
        provider = CsvPromptProvider(valid_csv)
        assert provider.total_count == 3
        assert provider.remaining_count == 3
        assert not provider.is_exhausted

    def test_initialization_with_missing_file(self, tmp_path: Path):
        """Test initialization fails when CSV file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.csv"
        with pytest.raises(FileNotFoundError):
            CsvPromptProvider(nonexistent)

    def test_initialization_with_empty_csv(self, empty_csv: Path):
        """Test initialization fails with empty CSV file."""
        with pytest.raises(PromptParseError, match="CSV file is empty"):
            CsvPromptProvider(empty_csv)

    def test_initialization_with_missing_columns(self, missing_columns_csv: Path):
        """Test initialization fails when CSV is missing required columns."""
        with pytest.raises(PromptParseError, match="'id' and 'prompt' columns"):
            CsvPromptProvider(missing_columns_csv)

    def test_initialization_with_header_only(self, header_only_csv: Path):
        """Test initialization succeeds with header-only CSV (zero prompts)."""
        provider = CsvPromptProvider(header_only_csv)
        assert provider.total_count == 0
        assert provider.remaining_count == 0
        assert provider.is_exhausted

    def test_poll_returns_prompts_in_order(self, valid_csv: Path):
        """Test that poll returns prompts in the correct order."""
        provider = CsvPromptProvider(valid_csv)

        prompt1 = provider.poll()
        assert prompt1 is not None
        assert prompt1.id == '1'
        assert prompt1.text == 'What is Python?'

        prompt2 = provider.poll()
        assert prompt2 is not None
        assert prompt2.id == '2'
        assert prompt2.text == 'Explain machine learning'

        prompt3 = provider.poll()
        assert prompt3 is not None
        assert prompt3.id == '3'
        assert prompt3.text == 'What is a REST API?'

    def test_poll_returns_none_when_exhausted(self, valid_csv: Path):
        """Test that poll returns None when all prompts are consumed."""
        provider = CsvPromptProvider(valid_csv)

        # Consume all prompts
        for _ in range(3):
            provider.poll()

        # Next poll should return None
        assert provider.poll() is None
        assert provider.is_exhausted

    def test_is_exhausted_property(self, valid_csv: Path):
        """Test the is_exhausted property accuracy."""
        provider = CsvPromptProvider(valid_csv)

        assert not provider.is_exhausted

        provider.poll()
        assert not provider.is_exhausted

        provider.poll()
        assert not provider.is_exhausted

        provider.poll()
        assert provider.is_exhausted

    def test_remaining_count_decreases(self, valid_csv: Path):
        """Test that remaining_count decreases as prompts are consumed."""
        provider = CsvPromptProvider(valid_csv)

        assert provider.remaining_count == 3
        provider.poll()
        assert provider.remaining_count == 2
        provider.poll()
        assert provider.remaining_count == 1
        provider.poll()
        assert provider.remaining_count == 0

    def test_total_count_stays_constant(self, valid_csv: Path):
        """Test that total_count remains constant."""
        provider = CsvPromptProvider(valid_csv)

        assert provider.total_count == 3
        provider.poll()
        assert provider.total_count == 3
        provider.poll()
        assert provider.total_count == 3
        provider.poll()
        assert provider.total_count == 3

    def test_context_manager(self, valid_csv: Path):
        """Test that provider works as a context manager."""
        with CsvPromptProvider(valid_csv) as provider:
            assert provider.total_count == 3
            prompt = provider.poll()
            assert prompt is not None
            assert prompt.id == '1'

    def test_context_manager_cleanup(self, valid_csv: Path):
        """Test that context manager calls close on exit."""
        provider = CsvPromptProvider(valid_csv)

        with provider:
            pass  # Context should call close on exit

        # Provider should still be usable after context exit
        # (close is a no-op for CSV provider)
        assert provider.total_count == 3

    def test_close_method(self, valid_csv: Path):
        """Test the close method (no-op for CSV provider)."""
        provider = CsvPromptProvider(valid_csv)
        provider.close()  # Should not raise any errors

        # Provider should still work after close
        assert provider.total_count == 3

    def test_poll_after_exhaustion_continues_returning_none(self, valid_csv: Path):
        """Test that poll continues to return None after exhaustion."""
        provider = CsvPromptProvider(valid_csv)

        # Consume all prompts
        for _ in range(3):
            provider.poll()

        # Multiple polls after exhaustion should all return None
        assert provider.poll() is None
        assert provider.poll() is None
        assert provider.poll() is None

    def test_with_unicode_content(self, tmp_path: Path):
        """Test handling CSV with unicode characters."""
        csv_file = tmp_path / "unicode.csv"
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'prompt'])
            writer.writeheader()
            writer.writerow({'id': '1', 'prompt': 'What is 日本語?'})
            writer.writerow({'id': '2', 'prompt': 'Explain émojis 🎉'})

        provider = CsvPromptProvider(csv_file)
        assert provider.total_count == 2

        prompt1 = provider.poll()
        assert prompt1.text == 'What is 日本語?'

        prompt2 = provider.poll()
        assert prompt2.text == 'Explain émojis 🎉'

    def test_with_multiline_prompts(self, tmp_path: Path):
        """Test handling CSV with prompts containing newlines."""
        csv_file = tmp_path / "multiline.csv"
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'prompt'])
            writer.writeheader()
            writer.writerow({'id': '1', 'prompt': 'Line 1\nLine 2'})

        provider = CsvPromptProvider(csv_file)
        prompt = provider.poll()
        assert 'Line 1\nLine 2' in prompt.text

    def test_pathlib_path_support(self, valid_csv: Path):
        """Test that provider accepts both string and Path objects."""
        # Test with Path object
        provider1 = CsvPromptProvider(valid_csv)
        assert provider1.total_count == 3

        # Test with string
        provider2 = CsvPromptProvider(str(valid_csv))
        assert provider2.total_count == 3


class TestCsvPromptProviderWatchMode:
    """Tests for CSV file watching functionality."""

    def test_watch_mode_detects_appends(self, tmp_path: Path):
        """Test that watch mode detects new rows appended to CSV."""
        csv_file = tmp_path / "prompts.csv"

        # Create initial CSV with one prompt
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'prompt'])
            writer.writeheader()
            writer.writerow({'id': '1', 'prompt': 'First prompt'})

        # Create provider in watch mode
        provider = CsvPromptProvider(
            csv_path=csv_file,
            watch_for_changes=True
        )

        # Poll first prompt
        prompt1 = provider.poll()
        assert prompt1 is not None
        assert prompt1.id == '1'

        # Poll again - should return None (no more data yet)
        prompt2 = provider.poll()
        assert prompt2 is None

        # Append new row to CSV
        with open(csv_file, 'a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'prompt'])
            writer.writerow({'id': '2', 'prompt': 'Second prompt'})

        # Poll again - should detect new row
        prompt3 = provider.poll()
        assert prompt3 is not None
        assert prompt3.id == '2'
        assert prompt3.text == 'Second prompt'

    def test_watch_mode_disabled_by_default(self, tmp_path: Path):
        """Test that watch mode is disabled by default."""
        csv_file = tmp_path / "prompts.csv"

        # Create CSV
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'prompt'])
            writer.writeheader()
            writer.writerow({'id': '1', 'prompt': 'First'})

        provider = CsvPromptProvider(csv_file)  # No watch_for_changes

        # Poll first
        provider.poll()

        # Append new row
        with open(csv_file, 'a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'prompt'])
            writer.writerow({'id': '2', 'prompt': 'Second'})

        # Poll again - should NOT detect new row (watch mode off)
        prompt = provider.poll()
        assert prompt is None
