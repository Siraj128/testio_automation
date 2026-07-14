FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

# Copy dependency definition first (Docker layer caching)
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Install Playwright browsers
RUN playwright install chromium

# Copy source code
COPY src/ ./src/
COPY config.yaml ./

# Create data directory structure
RUN mkdir -p data/browser_state data/browser_profile data/screenshots

# Expose dashboard port
EXPOSE 8500

# Run the bot
CMD ["python", "-m", "src.main"]
