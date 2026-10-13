# Public demo on Render (free web service, 512 MB RAM): the mini val scenes of nuScenes, every visitor's labels kept
# apart. Build context = repo root; the demo data comes from the Hugging Face dataset cuonglatao/m44-demo-data
# (made by deploy/hf/make_demo_data.py). Measured on Linux: ~340 MB RSS, starts in ~4 s.

FROM node:20-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
# opencv (pulled in by nuscenes-devkit) needs these even headless
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt huggingface_hub
ARG DEMO_DATA=cuonglatao/m44-demo-data
RUN mkdir -p /app/demo_data && python -c "from huggingface_hub import hf_hub_download; \
print(hf_hub_download('${DEMO_DATA}', 'm44-demo-data.tar', repo_type='dataset', local_dir='/tmp/dl'))" \
    && tar -xf /tmp/dl/m44-demo-data.tar -C /app/demo_data && rm -rf /tmp/dl /root/.cache
COPY . .
COPY --from=web /app/frontend/dist frontend/dist
ENV M44_DEMO=1 \
    M44_SPLITS=val \
    NUSC_ROOT=/app/demo_data/nuscenes \
    M44_DETS=/app/demo_data/dets \
    M44_DB=/tmp/m44_demo.db \
    MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1
WORKDIR /app/backend
# Render passes the port in $PORT (10000 by default)
CMD ["sh", "-c", "python -m uvicorn labeler.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
