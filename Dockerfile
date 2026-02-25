FROM python:3.12-slim

WORKDIR /app

# System deps (for requests / bs4 etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project
COPY . .

# Install uv
RUN pip install uv

# Install dependencies
RUN uv sync

# Expose webhook port
EXPOSE 8080

# Default command: telegram mode
CMD ["uv", "run", "python", "main.py", "telegram"]
