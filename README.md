# ChatGPT Automation Scraper

A fully automated scraper for ChatGPT answers with cited sources. This tool automates browser interactions with the ChatGPT web application to send prompts and extract responses including citations.

## What This Project Does

**ChatGPT Automation** is a production-ready scraper that:

- ✅ **Fully automated**: Send prompts to ChatGPT and scrape answers automatically
- ✅ **Citations extraction**: Extracts cited sources from ChatGPT responses
- ✅ **Multiple runs**: Run the same prompt multiple times for result consistency
- ✅ **Session rotation**: Distribute load across multiple Google accounts to avoid rate limits
- ✅ **Docker-ready**: Containerized deployment with virtual display

### Technology Stack

- **Playwright**: Browser automation framework for controlling Chromium
- **Docker + Xvfb**: Virtual display (`:99`) for running headful browsers in containers
- **Python 3.11**: Core programming language
- **uv**: Fast Python package manager

### How It Works

```
Input (CSV)          Processing                    Output (JSON)
┌──────────┐        ┌─────────────┐               ┌──────────────┐
│ Prompts  │───────>│  Playwright │──────────────>│  Answers +   │
│  .csv    │        │  + ChatGPT  │               │  Citations   │
└──────────┘        └─────────────┘               └──────────────┘
                         │
                    Xvfb Display :99
                    (Virtual Screen)
```

**Input**: CSV file with prompts to send to ChatGPT
**Processing**: Playwright automates browser, sends prompts, waits for responses, extracts citations
**Output**: JSON file with answers and cited sources for each prompt run

### Why Xvfb (Virtual Display :99)?

ChatGPT uses Cloudflare bot detection which blocks headless browsers. This scraper runs browsers in **headful mode** (with a visible window) to bypass detection. In Docker containers (which have no physical display), we use **Xvfb (X Virtual Framebuffer)** to create a fake display at `:99`, allowing headful browsers to run without a physical screen.

## Building the Docker Image

### Prerequisites

- Docker installed and running
- Session files from Google accounts (see Session Setup below)

### Build Command

```bash
docker build -t chatgpt-automation .
```

**What gets built:**
- Python 3.11 slim base image
- Xvfb for virtual display (`:99`)
- Playwright browser automation library
- Chromium browser with all dependencies
- Application scripts (`main.py`, `create_session.py`)

**Build time**: ~2-3 minutes (downloads Chromium browser)

### Verify Build

```bash
docker images | grep chatgpt-automation
```

You should see the image listed with tag `latest`.

## Running with Docker

### Session Setup (One-Time)

Before running with Docker, you need to create session files locally. Session files store authenticated login state (cookies) for ChatGPT.

**Create sessions for multiple Google accounts** (recommended for rate limit avoidance):

```bash
# Install dependencies locally
uv sync
uv run playwright install chromium

# Create session directory
mkdir sessions

# Create session files (manual login required for each)
uv run create_session.py --output sessions/account1.json
uv run create_session.py --output sessions/account2.json
uv run create_session.py --output sessions/account3.json
uv run create_session.py --output sessions/account4.json
```

Each command opens a browser window. Log in manually with a different Google account, then press Enter in the terminal. The session is saved to the specified `.json` file.

### Example: Run test_prompts.csv with Session Rotation

This example demonstrates running `test_prompts.csv` (5 prompts) with:
- **10 runs per prompt** = 50 total runs
- **Session change every 5 runs** (distributes load across 4 Google accounts)

```bash
docker run --rm \
  --shm-size=2gb \
  --security-opt seccomp:unconfined \
  -v $(pwd)/test_prompts.csv:/app/prompts.csv:ro \
  -v $(pwd)/sessions:/app/sessions:ro \
  -v $(pwd)/results:/app/results \
  chatgpt-automation \
  --input /app/prompts.csv \
  --sessions-dir /app/sessions \
  --runs 10 \
  --per-session-runs 5 \
  --output /app/results/test_results.json
```

**What this does:**
- Runs each of 5 prompts 10 times (50 total runs)
- Uses 4 sessions from `./sessions` directory
- Rotates sessions every 5 runs:
  - Runs 1-5: session 1 (account1.json)
  - Runs 6-10: session 2 (account2.json)
  - Runs 11-15: session 3 (account3.json)
  - Runs 16-20: session 4 (account4.json)
  - Runs 21-25: session 1 (cycles back)
  - ... and so on
- Saves results to `./results/test_results.json`

### Docker Arguments Explained

| Argument | Purpose |
|----------|---------|
| `--rm` | Remove container after run (cleanup) |
| `--shm-size=2gb` | Increase shared memory for Chromium (prevents crashes) |
| `--security-opt seccomp:unconfined` | Allow Chrome sandbox to work properly |
| `-v $(pwd)/test_prompts.csv:/app/prompts.csv:ro` | Mount input CSV (read-only) |
| `-v $(pwd)/sessions:/app/sessions:ro` | Mount sessions directory (read-only) |
| `-v $(pwd)/results:/app/results` | Mount results directory (read-write) |

### Application Arguments Explained

| Argument | Purpose | Example |
|----------|---------|---------|
| `--input` | Path to input CSV file | `/app/prompts.csv` |
| `--sessions-dir` | Directory with session files for rotation | `/app/sessions` |
| `--runs` | Number of times to run each prompt | `10` |
| `--per-session-runs` | Runs per session before switching | `5` |
| `--output` | Path to output JSON file | `/app/results/output.json` |

**Alternative: Single Session Mode** (no rotation):

```bash
docker run --rm \
  --shm-size=2gb \
  --security-opt seccomp:unconfined \
  -v $(pwd)/test_prompts.csv:/app/prompts.csv:ro \
  -v $(pwd)/sessions/account1.json:/app/session.json:ro \
  -v $(pwd)/results:/app/results \
  chatgpt-automation \
  --input /app/prompts.csv \
  --session-file /app/session.json \
  --runs 10 \
  --output /app/results/test_results.json
```

## Input Format

CSV file with columns: `id`, `prompt`

```csv
id,prompt
1,"Find me the best laptops under $1,000 with long battery life and at least 16GB of RAM"
2,"Compare the newest noise-canceling headphones and tell me which ones are best for commuting"
3,"I'm looking for a budget-friendly smartphone with a great camera—what should I buy?"
```

## Output Format

JSON file with nested structure:

```json
[
  {
    "prompt_id": "1",
    "prompt": "Find me the best laptops under $1,000 with long battery life and at least 16GB of RAM",
    "answers": [
      {
        "run_number": 1,
        "response": "Here are some excellent laptops under $1,000 with long battery life...",
        "citations": [
          {
            "url": "https://www.techradar.com/best-laptops",
            "text": "TechRadar - Best Laptops 2024"
          },
          {
            "url": "https://www.laptopmag.com/reviews",
            "text": "Laptop Mag - Reviews and Buying Guides"
          }
        ],
        "timestamp": "2024-01-20T10:30:00.123456"
      },
      {
        "run_number": 2,
        "response": "Based on current market analysis, these laptops stand out...",
        "citations": [
          {
            "url": "https://www.consumerreports.org/laptops",
            "text": "Consumer Reports - Laptop Ratings"
          }
        ],
        "timestamp": "2024-01-20T10:35:00.789012"
      }
    ]
  }
]
```

## Local Development (Without Docker)

### Installation

```bash
# Install dependencies
uv sync

# Install Playwright browsers
uv run playwright install chromium
```

### Usage

```bash
# Create a session file
uv run create_session.py --output session.json

# Run with single session
uv run main.py --session-file session.json --input prompts.csv --runs 3

# Run with session rotation
uv run main.py --sessions-dir ./sessions --input prompts.csv --runs 10 --per-session-runs 5
```

## Troubleshooting

### Session Expired

If you see "Session validation failed":
- Sessions expire after inactivity
- Re-run `create_session.py` to create fresh sessions
- You may need to log in again manually

### Cloudflare Detection

If ChatGPT detects automation:
- Ensure you're using valid session files
- Reduce `--per-session-runs` to switch sessions more frequently
- Add more session files to distribute load
- The Docker + Xvfb setup helps avoid detection

### Browser Crashes in Docker

If Chromium crashes:
- Increase `--shm-size` to `4gb` or higher
- Ensure Docker has sufficient memory allocated (Settings → Resources)
- Check Docker logs: `docker logs <container-id>`

### No Citations Extracted

Citations only appear when:
- You're logged in (session file is valid)
- ChatGPT decides to cite sources (not guaranteed for every prompt)
- The response includes sources (depends on prompt type)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Container                      │
│                                                          │
│  ┌──────────┐         ┌────────────┐                    │
│  │  Xvfb    │────────>│ Chromium   │                    │
│  │ Display  │         │ (Headful)  │                    │
│  │   :99    │         └────────────┘                    │
│  └──────────┘               │                           │
│                              │                           │
│                        ┌─────▼──────┐                   │
│                        │ Playwright │                   │
│                        │ Automation │                   │
│                        └─────┬──────┘                   │
│                              │                           │
│                        ┌─────▼──────┐                   │
│                        │  main.py   │                   │
│                        │  (Python)  │                   │
│                        └────────────┘                   │
│                                                          │
└─────────────────────────────────────────────────────────┘
                          │           │
                    Input CSV    Output JSON
                     (Prompts)   (Answers + Citations)
```

**Components:**
- **Xvfb**: Virtual X11 display server (fake screen at `:99`)
- **Chromium**: Full web browser (headful mode to bypass Cloudflare)
- **Playwright**: Browser automation library (controls Chromium)
- **main.py**: Python script orchestrating the automation
- **Session files**: Stored authentication state (cookies, localStorage)

## License

MIT
