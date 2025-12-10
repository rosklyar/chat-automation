# AI-assistants Answers Platform

## Why

This platform provides a scalable service for retrieving answers from multiple AI assistants (ChatGPT, Claude, Google AI Overview, Perplexity).


- Prompts submitted to the system via Kafka. Now implemented simpler approach with polling service API by automation-bot.
- Platform provides answers instantly for prompts which are already in db(which means were executed before).
- Platform suggests user to use prompts which are similar to requested, for which we already have data.
- New prompts(no similarity >= 0.95 in db) are automatically scheduled for execution across AI assistants. Answers is going to be served as soon as they ready with a callback.
- Answers are stored and become available for future requests.

## Overall Architecture

![Architecture Diagram](ai-assistants-answers-arch.png)

### Main Flows

1. **Session Creation Flow**
   - Backoffice operator creates logins to AI-assistant with created credentials → `session-creation-frontend` → `chat-session-provider` → PostgreSQL (`sessions-db`)
   - Creates and stores authenticated session files for automation bots

2. **Answer Request Flow**
   - Customer → `answers-provider` → PostgreSQL + pgvector (`prompts-db` + `llm-answers-db`)
   - Searches for similar prompts (similarity > 0.95) and returns cached answers instantly if user agreed to use similar
   - Returns existing answers and notifies when answers for new prompts are ready

3. **Automation Flow**
   - `prompts-scheduler` → Kafka (`prompts-tasks`) → `automation-bot` instances (scalable)
   - prompts-scheduler reads prompts which were requested by any client and creates tasks as kafka messages which contains all needed info for automation-bot to evaluate answers
   - Bots get sessions from `chat-session-provider` according to specific info in prompts-tasks(for example target account preferences)
   - Bots execute prompts and produce results to Kafka (`llm-answers`)
   - `kafka-connector-for-postgres` writes answers to PostgreSQL (`llm-answers-db`) with prompt_id foreign key

### Technologies

- **Frontend**: Session creation UI: React
- **Backend Services**: Python-based microservices (chat-session-provider, answers-provider, prompts-scheduler)
- **Databases**: PostgreSQL (sessions as json), PostgreSQL + pgvector (vector similarity search for prompts)
- **Message Queue**: Apache Kafka (prompts-tasks, llm-answers topics)
- **Automation**: Playwright-based bots running in Docker containers
- **Data Integration**: Kafka Connect for PostgreSQL

### Microservices

| Service | Purpose |
|---------|---------|
| `session-creation-frontend` | UI for creating authenticated sessions |
| `chat-session-provider` | Manages and provides bot session files |
| `answers-provider` | Searches cached answers using vector similarity |
| `prompts-scheduler` | Schedules prompt execution tasks to Kafka |
| `automation-bot` | Scalable workers that execute prompts on AI assistants |
| `kafka-connector-for-postgres` | Syncs Kafka messages to PostgreSQL |

## ChatGPT Bot (Current Implementation)

The ChatGPT automation bot is fully implemented and uses:
- **Playwright** for browser automation
- **Docker + Xvfb** for headful browser execution (bypasses Cloudflare detection)
- **Session rotation** to distribute load across multiple Google accounts
- **HTTP API polling** for continuous prompt processing with atomic claim semantics

### Build Docker Image

```bash
docker build -t chatgpt-automation .
```

### Run with Docker

**Prerequisites:** Create session files locally first:

```bash
uv sync
uv run playwright install chromium
mkdir sessions

# Create sessions for multiple accounts
uv run scripts/create_session.py --output sessions/account1.json
uv run scripts/create_session.py --output sessions/account2.json
uv run scripts/create_session.py --output sessions/account3.json
```

**Run in HTTP API polling mode (continuous operation):**

```bash
docker run --rm \
  --shm-size=2gb \
  --security-opt seccomp:unconfined \
  -v $(pwd)/sessions:/app/sessions:ro \
  chatgpt-automation \
  --sessions-dir /app/sessions \
  --api-url http://your-backend-api:8000 \
  --results-api-url http://your-backend-api:8000 \
  --assistant-name ChatGPT \
  --plan-name Plus \
  --max-attempts 3 \
  --per-session-runs 10 \
  --poll-retry-seconds 10 \
  --idle-timeout-minutes 30
```

**How it works:**

The bot runs continuously, polling the backend API for prompts:

1. **Poll for prompt** - Sends POST request to `/evaluations/api/v1/poll` with assistant and plan preferences
   - Returns prompt with `evaluation_id` when available
   - Returns empty response when queue is empty (non-blocking)

2. **Get session** - Selects next session from the pool using round-robin rotation
   - Automatically switches sessions after `--per-session-runs` evaluations

3. **Initialize browser** - Loads authenticated session (cookies + storage)
   - Handles any authentication modals automatically

4. **Evaluation loop** - Attempts to get response with citations (up to `--max-attempts` times)
   - Starts new conversation for each retry
   - Extracts citations from ChatGPT response
   - If citations found → proceed to submit

5. **Force retry with fresh session** - After max attempts exhausted
   - Switches to a new session
   - Tries one final time

6. **Submit result** - Two paths based on success:
   - **Success (has citations)**: POST to `/evaluations/api/v1/submit` with answer and citations
   - **Failure (no citations)**: POST to `/evaluations/api/v1/release` to mark evaluation as failed

7. **Wait and repeat** - When no prompts available, waits `--poll-retry-seconds` before next poll

**Graceful shutdown:**
- Press Ctrl+C to stop processing
- Browser closes after `--idle-timeout-minutes` of inactivity (if specified)

### HTTP API Integration

The bot integrates with the backend API service using a continuous polling mechanism. This enables atomic claim semantics and distributed processing across multiple bot instances.

#### API Endpoints

**1. Poll for Prompts**
- **Endpoint:** `POST /evaluations/api/v1/poll`
- **Purpose:** Claim next available prompt evaluation
- **Request:**
  ```json
  {
    "assistant_name": "ChatGPT",
    "plan_name": "Plus"
  }
  ```
- **Response (prompt available):**
  ```json
  {
    "evaluation_id": 123,
    "prompt_id": 456,
    "prompt_text": "What are the best laptops under $1,000?",
    "topic_id": 1,
    "claimed_at": "2025-12-09T10:30:00Z"
  }
  ```
- **Response (no prompts):**
  ```json
  {
    "evaluation_id": null,
    "prompt_id": null,
    "prompt_text": null,
    "topic_id": null,
    "claimed_at": null
  }
  ```

**2. Submit Successful Evaluation**
- **Endpoint:** `POST /evaluations/api/v1/submit`
- **Purpose:** Submit answer with citations
- **Request:**
  ```json
  {
    "evaluation_id": 123,
    "answer": {
      "response": "Here are excellent laptops under $1,000...",
      "citations": [
        {
          "url": "https://example.com/laptop-review",
          "text": "TechRadar: Best Budget Laptops 2025"
        }
      ],
      "timestamp": "2025-12-09T10:35:00Z"
    }
  }
  ```
- **Response:**
  ```json
  {
    "evaluation_id": 123,
    "status": "submitted"
  }
  ```

**3. Release Failed Evaluation**
- **Endpoint:** `POST /evaluations/api/v1/release`
- **Purpose:** Release evaluation back to queue when unable to get citations
- **Request:**
  ```json
  {
    "evaluation_id": 123,
    "mark_as_failed": true,
    "failure_reason": "No citations found after 3 attempts"
  }
  ```
- **Response:**
  ```json
  {
    "evaluation_id": 123,
    "action": "released"
  }
  ```

### How it runs as a Docker image and can be scaled

https://github.com/user-attachments/assets/a09b8bb0-af95-4ee1-aa93-09c393372a1a

## Quick Reference

### Local Development

```bash
# Install dependencies
uv sync
uv run playwright install chromium

# Create sessions (one or more)
mkdir sessions
uv run scripts/create_session.py --output sessions/account1.json

# Run automation with HTTP API polling
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
```

### Docker Arguments

| Argument | Purpose |
|----------|---------|
| `--shm-size=2gb` | Increase shared memory for Chromium |
| `--security-opt seccomp:unconfined` | Allow Chrome sandbox |
| `-v $(pwd)/sessions:/app/sessions:ro` | Mount sessions directory (read-only) |

### Application Arguments

| Argument | Purpose | Example | Required |
|----------|---------|---------|----------|
| `--api-url` | Base URL for HTTP API prompt source | `http://localhost:8000` | **Yes** |
| `--results-api-url` | Base URL for HTTP API result submission | `http://localhost:8000` | **Yes** |
| `--sessions-dir` | Directory with session files | `/app/sessions` | **Yes** |
| `--assistant-name` | Assistant name for API requests | `ChatGPT` | No (default: `ChatGPT`) |
| `--plan-name` | Plan name for API requests | `Plus` | No (default: `Plus`) |
| `--max-attempts` | Max attempts to get citations per prompt | `3` | No (default: `1`) |
| `--per-session-runs` | Evaluations per session before rotation | `10` | No (default: `10`) |
| `--poll-retry-seconds` | Seconds to wait when no prompts available | `10` | No (default: `5.0`) |
| `--idle-timeout-minutes` | Close browser after N minutes of inactivity | `30` | No (default: never) |
| `--api-timeout` | API request timeout in seconds | `30.0` | No (default: `30.0`) |
| `--submit-retry-attempts` | Max retry attempts for submitting results | `3` | No (default: `3`) |
| `--submit-timeout` | Result submission timeout in seconds | `30.0` | No (default: `30.0`) |
| `--log-level` | Logging level | `INFO` | No (default: `INFO`) |
| `--log-file` | Optional log file path | `/app/logs/bot.log` | No (default: console only) |
