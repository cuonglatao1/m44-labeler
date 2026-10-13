# Public demo on Hugging Face Spaces (Docker SDK): the mini val scenes of nuScenes, every visitor's labels kept apart.
# Build context = the folder made by deploy/hf/stage_space.py (repo files + demo_data/).

FROM node:20-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
# opencv (pulled in by nuscenes-devkit) needs these even headless
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user . .
COPY --from=web --chown=user /app/frontend/dist frontend/dist
USER user
ENV M44_DEMO=1 \
    M44_SPLITS=val \
    NUSC_ROOT=/app/demo_data/nuscenes \
    M44_DETS=/app/demo_data/dets \
    M44_DB=/tmp/m44_demo.db \
    MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /app/backend
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "labeler.main:app", "--host", "0.0.0.0", "--port", "7860"]
