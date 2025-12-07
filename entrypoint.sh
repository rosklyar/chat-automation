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

# Run the Python script directly, passing all arguments
python -m src.bot "$@"

# Capture exit code
EXIT_CODE=$?

# Clean up Xvfb
kill $XVFB_PID 2>/dev/null || true

exit $EXIT_CODE
