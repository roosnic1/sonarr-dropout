FROM python:3.14-slim@sha256:656d12e70054d5fda18a045e2494c96701e9792dd1445f95b3d038df954f57e9

# Set working directory
WORKDIR /app

# Install system dependencies
# ffmpeg is required by yt-dlp to mux/remux the separate video and audio
# streams dropout.tv (Vimeo OTT) serves
RUN apt-get update && apt-get install -y \
    gcc \
    libxml2-dev \
    libxslt-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml first for dependency layer caching
COPY pyproject.toml ./
COPY sonarr_dropout/__init__.py sonarr_dropout/__version__.py sonarr_dropout/

# Install runtime dependencies only
RUN pip install --no-cache-dir .

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose the service port
EXPOSE 8080

# Health check -- verify HTTP server is listening (no API calls)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8080/health')" || exit 1

# Run the application
CMD ["python", "-m", "sonarr_dropout.main"]