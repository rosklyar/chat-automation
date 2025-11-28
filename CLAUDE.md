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
uv run src/create_session.py --output sessions/account1.json

# Run the main application with saved sessions
uv run src/bot.py --sessions-dir sessions --input prompts.csv --max-attempts 3

# Run tests
uv run pytest

# Add a new dependency
uv add <package-name>

# Add a development dependency
uv add --dev <package-name>

# Sync dependencies
uv sync
```

## Session Management

The project includes two main scripts:

1. **src/create_session.py** - Create authenticated session files
2. **src/bot.py** - Run automation with saved sessions

### Creating Sessions

Create session files for different Google accounts to avoid rate limits:

```bash
# Create sessions for multiple accounts
uv run src/create_session.py --output session_account1.json
uv run src/create_session.py --output session_account2.json
uv run src/create_session.py --output session_account3.json

# Or organize them in a directory
mkdir sessions
uv run src/create_session.py --output sessions/account1.json
uv run src/create_session.py --output sessions/account2.json
uv run src/create_session.py --output sessions/account3.json
uv run src/create_session.py --output sessions/account4.json
```

Each session file stores the authenticated state (cookies, storage) for reuse.

### Using Sessions

The bot always uses session rotation mode - simply provide a directory with one or more session files.

**For single session:** Put one file in the directory
**For rotation:** Put multiple files in the directory

The bot automatically attempts to get answers **with citations** for each prompt:

```bash
# Try up to 3 times per prompt to get citations
# 4 sessions in ./sessions directory
# --per-session-runs 10 means each session handles 10 attempts before switching

uv run src/bot.py --sessions-dir ./sessions --input prompts.csv --max-attempts 3 --per-session-runs 10
```

**How it works:**
- For each prompt, tries up to `--max-attempts` times to get an answer with citations
- If no citations after max attempts, switches to a new session and tries once more
- If still no citations, saves empty response and moves to next prompt
- Sessions rotate automatically after `--per-session-runs` attempts

**Key Parameters:**
- `--sessions-dir PATH` - Directory containing session .json files
- `--max-attempts N` - Maximum attempts to get citations per prompt (default: 1)
- `--per-session-runs N` - Number of attempts per session before switching (default: 10)

### Benefits

- ✅ **Avoid rate limits** - Distribute load across multiple Google accounts
- ✅ **Automatic rotation** - Script handles session switching automatically
- ✅ **Cycle indefinitely** - Sessions are reused in round-robin fashion
- ✅ **No manual intervention** - Set it and forget it
- ✅ **Unified approach** - Single or multiple sessions use the same `--sessions-dir` parameter

## Architecture

- **Automation Framework**: Playwright is the chosen framework for browser automation
- **Target**: ChatGPT web application (rich client interface)
- **Core Functionality**: Send prompts to ChatGPT and extract/scrape responses
