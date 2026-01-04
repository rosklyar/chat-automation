#!/bin/bash
set -e

# Start Xvfb (X Virtual Frame Buffer) on display :99
echo "Starting Xvfb..."
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Wait for Xvfb to start
sleep 2

# Export DISPLAY for applications to use
export DISPLAY=:99

echo "Running ChatGPT automation..."

# Build command with environment variables (with defaults)
CMD="python -m src.bot"
CMD="$CMD --sessions-dir ${SESSIONS_DIR:-/app/sessions}"
CMD="$CMD --api-url ${API_URL:?API_URL environment variable is required}"
CMD="$CMD --results-api-url ${RESULTS_API_URL:?RESULTS_API_URL environment variable is required}"
CMD="$CMD --assistant-name ${ASSISTANT_NAME:-ChatGPT}"
CMD="$CMD --plan-name ${PLAN_NAME:-Plus}"
CMD="$CMD --max-attempts ${MAX_ATTEMPTS:-3}"
CMD="$CMD --per-session-runs ${PER_SESSION_RUNS:-10}"

# Polling backoff configuration
CMD="$CMD --poll-base-interval ${POLL_BASE_INTERVAL:-5}"
CMD="$CMD --poll-max-interval ${POLL_MAX_INTERVAL:-300}"
CMD="$CMD --poll-backoff-multiplier ${POLL_BACKOFF_MULTIPLIER:-2.0}"
CMD="$CMD --api-error-retry-interval ${API_ERROR_RETRY_INTERVAL:-300}"
CMD="$CMD --browser-close-threshold ${BROWSER_CLOSE_THRESHOLD:-60}"

# Bot secret is required for API authentication
CMD="$CMD --bot-secret ${BOT_SECRET:?BOT_SECRET environment variable is required}"

# Execute with any additional CLI arguments
eval $CMD "$@"

# Capture exit code
EXIT_CODE=$?

# Clean up Xvfb
kill $XVFB_PID 2>/dev/null || true

exit $EXIT_CODE
