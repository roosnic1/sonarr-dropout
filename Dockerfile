FROM python:3.11-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

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
COPY pyproject.toml __version__.py ./

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
CMD ["python", "main.py"]