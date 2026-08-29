FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Config/labels are persisted here - mount this as a volume so they
# survive container recreation (see docker-compose.yml).
ENV CONFIG_DIR=/data
RUN mkdir -p /data

# Runs as root intentionally: the app needs to read whatever SSH private
# key file you bind-mount in for key-based login, and matching that
# mounted file's host ownership to a non-root container user is more
# support burden than it's worth for a single-user internal tool.
EXPOSE 8000

CMD ["python", "app.py"]
