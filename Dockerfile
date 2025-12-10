# Use slim Python image for smaller size
FROM python:3.11-slim

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies for Playwright and Xvfb
RUN apt-get update && apt-get install -y \
    xvfb \
    wget \
    # Chromium dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install uv for dependency management
RUN pip install --no-cache-dir uv

# Copy Python dependencies files
COPY pyproject.toml uv.lock ./

# Install all Python dependencies using uv
RUN uv pip install --system -r pyproject.toml

# Install Playwright Chromium browser
RUN playwright install chromium --with-deps

# Copy application files
COPY src/ ./src/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Set display for Xvfb
ENV DISPLAY=:99

# Run entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
