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
uv run src/bot.py --sessions-dir sessions --input prompts.csv --runs 3

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

Automatically rotates through sessions to distribute load and avoid rate limits:

```bash
# Run 10 prompts with 5 runs each = 50 total runs
# 4 sessions in ./sessions directory
# --per-session-runs 10 means each session handles 10 runs before switching

uv run src/bot.py --sessions-dir ./sessions --input prompts.csv --runs 5 --per-session-runs 10
```

**How it works:**
- Session 1: runs 1-10 (first 2 prompts × 5 runs each)
- Session 2: runs 11-20 (next 2 prompts × 5 runs each)
- Session 3: runs 21-30 (next 2 prompts × 5 runs each)
- Session 4: runs 31-40 (next 2 prompts × 5 runs each)
- Session 1 (again): runs 41-50 (last 2 prompts × 5 runs each)

**Session Rotation Parameters:**
- `--sessions-dir PATH` - Directory containing session .json files
- `--per-session-runs N` - Number of runs per session before switching (default: 10)

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
