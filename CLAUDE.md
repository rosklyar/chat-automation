# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project automates interactions with the ChatGPT web application using Playwright to send prompts and scrape responses via the rich client interface.

## Development Setup

**Package Management**: This project uses `uv` for all dependency management and script execution. See https://docs.astral.sh/uv/

**Python Version**: Requires Python >= 3.13

## Common Commands

```bash
# Run the main application
uv run main.py

# Add a new dependency
uv add <package-name>

# Add a development dependency
uv add --dev <package-name>

# Sync dependencies
uv sync
```

## Architecture

- **Automation Framework**: Playwright is the chosen framework for browser automation
- **Target**: ChatGPT web application (rich client interface)
- **Core Functionality**: Send prompts to ChatGPT and extract/scrape responses
