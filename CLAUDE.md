# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project automates interactions with the ChatGPT web application using Playwright to send prompts and scrape responses via the rich client interface.

## Development Setup

**Package Management**: This project uses `uv` for all dependency management and script execution. See https://docs.astral.sh/uv/

**Python Version**: Requires Python >= 3.11

## Common Commands

```bash
# Create a session file (manual login)
uv run create_session.py --output session.json

# Run the main application with a saved session
uv run main.py --session-file session.json --input prompts.csv --runs 3

# Add a new dependency
uv add <package-name>

# Add a development dependency
uv add --dev <package-name>

# Sync dependencies
uv sync
```

## Session Management

The project includes two main scripts:

1. **create_session.py** - Create authenticated session files
2. **main.py** - Run automation with saved sessions

### Creating Sessions

Create session files for different Google accounts to avoid rate limits:

```bash
# Create sessions for multiple accounts
uv run create_session.py --output session_account1.json
uv run create_session.py --output session_account2.json
uv run create_session.py --output session_account3.json

# Or organize them in a directory
mkdir sessions
uv run create_session.py --output sessions/account1.json
uv run create_session.py --output sessions/account2.json
uv run create_session.py --output sessions/account3.json
uv run create_session.py --output sessions/account4.json
```

Each session file stores the authenticated state (cookies, storage) for reuse.

### Using Sessions

#### Single Session Mode

Use a single session file (legacy mode):

```bash
uv run main.py --session-file session_account1.json --input prompts.csv --runs 3
```

#### Session Rotation Mode (Recommended)

Automatically rotate through multiple sessions to distribute load and avoid rate limits:

```bash
# Run 10 prompts with 5 runs each = 50 total runs
# 4 sessions in ./sessions directory
# --per-session-runs 10 means each session handles 10 runs before switching

uv run main.py --sessions-dir ./sessions --input prompts.csv --runs 5 --per-session-runs 10
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
- ✅ **Backward compatible** - Single session mode still works with `--session-file`

## Architecture

- **Automation Framework**: Playwright is the chosen framework for browser automation
- **Target**: ChatGPT web application (rich client interface)
- **Core Functionality**: Send prompts to ChatGPT and extract/scrape responses
