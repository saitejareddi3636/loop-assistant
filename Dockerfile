# Multi-stage production image: Vite UI + FastAPI (+ optional local voice).
FROM node:22-bookworm AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS api
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./requirements.txt
COPY api/requirements-voice.txt ./requirements-voice.txt
RUN pip install -r requirements.txt \
    && pip install -r requirements-voice.txt

COPY api/app ./app
COPY api/scripts ./scripts
COPY --from=web-build /web/dist ./web_dist

ENV LLM_PROVIDER=groq \
    VOICE_BACKEND=auto \
    EMBEDDING_PROVIDER=hash

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
