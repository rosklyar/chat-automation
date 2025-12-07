"""Input/output utilities for prompt reading and result saving."""

import csv
import json
from pathlib import Path

from .models import Prompt, EvaluationResult


def read_prompts_from_csv(csv_path: str | Path) -> list[Prompt]:
    """
    Read prompts from CSV file.

    Args:
        csv_path: Path to CSV file with columns: id, prompt

    Returns:
        List of Prompt objects
    """
    prompts = []
    csv_path = Path(csv_path)

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                prompts.append(Prompt(id=row['id'], text=row['prompt']))
        print(f"Loaded {len(prompts)} prompts from {csv_path}")
    except FileNotFoundError:
        print(f"Error: File {csv_path} not found")
    except KeyError as e:
        print(f"Error: Missing column in CSV: {e}")
    except Exception as e:
        print(f"Error reading CSV: {e}")

    return prompts


class ResultWriter:
    """
    Handles saving evaluation results to JSON file.

    Output format:
    [
        {
            "prompt_id": "1",
            "prompt": "...",
            "answers": [
                {
                    "run_number": 1,
                    "response": "...",
                    "citations": [{"url": "...", "text": "..."}],
                    "timestamp": "..."
                }
            ]
        }
    ]
    """

    def __init__(self, output_path: str | Path) -> None:
        """
        Initialize the result writer.

        Args:
            output_path: Path to output JSON file.
        """
        self._output_path = Path(output_path)
        self._data: list[dict] = self._load_existing()

    def _load_existing(self) -> list[dict]:
        """Load existing results if file exists."""
        if self._output_path.exists():
            try:
                with open(self._output_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
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

    def _save(self) -> None:
        """Write data to file."""
        with open(self._output_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        print(f"Results saved to {self._output_path}")

    def save_result(
        self,
        prompt: Prompt,
        result: EvaluationResult,
        run_number: int,
    ) -> None:
        """
        Save a successful evaluation result.

        Args:
            prompt: The prompt that was evaluated.
            result: The evaluation result.
            run_number: The attempt number.
        """
        entry = self._find_or_create_entry(prompt)
        entry['answers'].append({
            'run_number': run_number,
            'response': result.response_text,
            'citations': [c.to_dict() for c in result.citations],
            'timestamp': result.timestamp.isoformat(),
        })
        self._save()

    def save_empty_result(self, prompt: Prompt) -> None:
        """
        Save prompt with empty answers when all attempts failed.

        Args:
            prompt: The prompt that failed to get citations.
        """
        print(f"Saving empty result for prompt {prompt.id}")
        self._find_or_create_entry(prompt)  # Ensures entry exists with empty answers
        self._save()
