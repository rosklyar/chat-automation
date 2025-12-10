# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project automates interactions with the ChatGPT web application using Playwright to send prompts and scrape responses via the rich client interface.

## Development Setup

**Package Management**: This project uses `uv` for all dependency management and script execution. See https://docs.astral.sh/uv/

**Python Version**: Requires Python >= 3.11

## Common Commands

```bash
# Create session files (manual login)
mkdir sessions
uv run scripts/create_session.py --output sessions/account1.json

# Run the main application with HTTP API endpoints
uv run src/bot.py \
  --sessions-dir sessions \
  --api-url http://localhost:8000 \
  --results-api-url http://localhost:8000 \
  --assistant-name ChatGPT \
  --plan-name Plus \
  --max-attempts 3 \
  --poll-retry-seconds 10 \
  --idle-timeout-minutes 30

# Run tests
uv run pytest

# Add a new dependency
uv add <package-name>

# Add a development dependency
uv add --dev <package-name>

# Sync dependencies
uv sync
```

## Project Structure

```
chat-automation/
    scripts/
        create_session.py          # Standalone utility for session creation
    src/
        __init__.py                # Package exports
        models.py                  # Data classes (SessionType, Citation, EvaluationResult, etc.)
        session_provider.py        # SessionProvider protocol + FileSessionProvider
        bot_interface.py           # Bot protocol definition
        prompt_provider.py         # PromptProvider protocol + HttpApiPromptProvider
        result_persister.py        # ResultPersister protocol + HttpApiResultPersister
        shutdown_handler.py        # Graceful shutdown handling
        logging_config.py          # Logging configuration
        bot.py                     # Main orchestration (Orchestrator class)
        chatgpt/
            __init__.py            # ChatGPT package exports
            bot.py                 # ChatGPTBot implementation
            auth.py                # Authentication handling (modals, login)
            citation_extractor.py  # Citation/source extraction
    tests/
        ...
```

## Key Abstractions

### SessionProvider
Manages session lifecycle, rotation, and usage tracking.
- `get_session(session_type)` - Get available session
- `record_evaluation(session_id)` - Track usage, returns remaining count
- `mark_invalid(session_id)` - Mark session as expired

### Bot Protocol
Interface for AI assistant automation.
- `initialize(session_info)` - Load session and authenticate
- `evaluate(prompt)` - Send prompt, get response with citations
- `start_new_conversation()` - Clear context for retry
- `close()` - Release resources

### ChatGPTBot
Implementation of Bot protocol for ChatGPT web automation.
- Uses Playwright for browser control
- Handles authentication modals automatically
- Extracts citations from responses

### PromptProvider
Protocol for sourcing prompts from various sources.
- `poll() -> Optional[Prompt]` - Get next prompt if available
- `is_exhausted` property - Check if source has no more prompts
- `close()` - Release resources (connections)
- **HttpApiPromptProvider**: Polls HTTP API endpoint for prompts, supports continuous polling

### ResultPersister
Protocol for persisting evaluation results to various backends.
- `save(prompt, result, run_number)` - Persist a single evaluation result
- `output_location` property - Human-readable description of storage location
- `close()` - Ensure all data is persisted and release resources
- **HttpApiResultPersister**: Submits results to HTTP API endpoints (submit for success, release for failures)

### ShutdownHandler
Manages graceful shutdown for long-running processes.
- `should_shutdown` property - Check if shutdown has been requested
- `shutdown_event` property - Threading.Event for interruptible waits
- `install_signal_handlers()` - Register SIGINT/SIGTERM handlers
- Enables Ctrl+C graceful shutdown in continuous mode

## Session Management

### Creating Sessions

The `scripts/create_session.py` utility creates authenticated session files:

```bash
# Create sessions for multiple accounts
mkdir sessions
uv run scripts/create_session.py --output sessions/account1.json
uv run scripts/create_session.py --output sessions/account2.json
uv run scripts/create_session.py --output sessions/account3.json
```

Each session file stores the authenticated state (cookies, storage) for reuse.

### Using Sessions

The bot uses session rotation mode - provide a directory with session files.

```bash
# Try up to 3 times per prompt to get citations
# --per-session-runs 10 means each session handles 10 attempts before switching

uv run src/bot.py \
  --sessions-dir ./sessions \
  --api-url http://localhost:8000 \
  --results-api-url http://localhost:8000 \
  --assistant-name ChatGPT \
  --plan-name Plus \
  --max-attempts 3 \
  --per-session-runs 10
```

**How it works:**
- Polls HTTP API endpoint for prompts continuously
- For each prompt, tries up to `--max-attempts` times to get an answer with citations
- If no citations after max attempts, switches to a new session and tries once more
- If still no citations, releases evaluation as failed via API
- Sessions rotate automatically after `--per-session-runs` attempts

**Key Parameters:**
- `--sessions-dir PATH` - Directory containing session .json files (required)
- `--api-url URL` - Base URL for HTTP API prompt source (required)
- `--results-api-url URL` - Base URL for HTTP API result submission (required)
- `--assistant-name NAME` - Assistant name for API requests (default: ChatGPT)
- `--plan-name NAME` - Plan name for API requests (default: Plus)
- `--max-attempts N` - Maximum attempts to get citations per prompt (default: 1)
- `--per-session-runs N` - Number of attempts per session before switching (default: 10)
- `--poll-retry-seconds N` - Seconds to wait when no prompts available (default: 5.0)
- `--idle-timeout-minutes N` - Close browser after N minutes of inactivity (default: never)

### Benefits

- Avoid rate limits - Distribute load across multiple accounts
- Automatic rotation - Session switching handled automatically
- Round-robin cycling - Sessions reused indefinitely
- Clean separation - Session management decoupled from bot logic

## Operating Mode

### Continuous API Polling
The bot runs continuously, polling the HTTP API for new prompts.

```bash
uv run src/bot.py \
  --sessions-dir sessions \
  --api-url http://localhost:8000 \
  --results-api-url http://localhost:8000 \
  --assistant-name ChatGPT \
  --plan-name Plus \
  --poll-retry-seconds 10 \
  --idle-timeout-minutes 30 \
  --max-attempts 3
```

**How it works:**
- Polls HTTP API endpoint continuously for new prompts
- Returns None when no prompts available (non-blocking)
- Waits `--poll-retry-seconds` before retrying when queue is empty
- Closes browser after `--idle-timeout-minutes` of inactivity to save resources
- Press Ctrl+C for graceful shutdown
- Never exhausts - `is_exhausted` always returns False

## Architecture

- **Automation Framework**: Playwright for browser automation
- **Target**: ChatGPT web application (rich client interface)
- **Design**: SOLID principles with Protocol-based abstractions
- **Extensibility**: Easy to add new AI providers (implement Bot protocol)
