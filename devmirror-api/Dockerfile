FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y curl ca-certificates bash tar && rm -rf /var/lib/apt/lists/*

# Install Coral CLI v0.4.1 directly from GitHub releases (reliable, no install script needed)
RUN curl -fsSL https://github.com/withcoral/coral/releases/download/v0.4.1/coral-x86_64-unknown-linux-gnu.tar.gz \
    | tar -xz -C /usr/local/bin && \
    chmod +x /usr/local/bin/coral && \
    coral --version

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

RUN chmod +x /app/start.sh

EXPOSE 8000

ENTRYPOINT ["/bin/bash", "/app/start.sh"]
