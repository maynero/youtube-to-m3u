FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create a non-root user and switch to it
RUN useradd -m appuser && chown -R appuser /app
USER appuser

ENV PYTHONUNBUFFERED 1

EXPOSE 6095

# Specify the command to run your application
CMD ["python", "streamlink-m3u.py"]
