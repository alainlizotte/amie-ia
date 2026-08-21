# Image monorepo Ami(e) IA — Compagnon virtuel (FastAPI + React build statique).
# Construit depuis la racine du projet :
#   docker build -t amie-ia .
# Usage normal via docker-compose.yml (cf. ce fichier).

FROM python:3.12-slim

WORKDIR /app

# Dépendances Python (pré-copiées pour bénéficier du cache Docker).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif serveur + frontend buildé (client/ → server/static via Vite).
# config/, server/data/ et data/character_presets/ sont montés en volumes.
COPY server/ ./server/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AMIE_CONFIG=/app/config/config.yaml

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request, sys; \
        sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=3).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-ping-interval", "30", "--ws-ping-timeout", "60"]
