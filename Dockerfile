# --- Étape 1 : build du front React (Vite) ---
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Étape 2 : runtime Python (web + worker partagent cette image) ---
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt
COPY backend/ ./backend/
COPY scripts/ ./scripts/
# le front buildé, servi par FastAPI (api.py monte frontend/dist en statique)
COPY --from=frontend /app/frontend/dist ./frontend/dist
ENV PYTHONUNBUFFERED=1
# WEB par défaut. Le service WORKER surcharge la commande par : python -m backend.worker
CMD ["sh", "-c", "uvicorn backend.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
