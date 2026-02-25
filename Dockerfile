FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY dependency files first (critical for caching)
COPY pyproject.toml uv.lock ./

# Install uv
RUN pip install --no-cache-dir uv

# Install dependencies
RUN uv sync

# Now copy rest of project
COPY . .

EXPOSE 8080

CMD ["uv", "run", "python", "main.py", "telegram"]