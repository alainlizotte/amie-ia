# Ami(e) IA — Rencontres virtuelles (serveur dédié)

Application de simulation de rencontre inspirée du projet OpenWebUI « Ami(e) IA »,
reconstruite en **serveur dédié** sur le modèle du projet « d&d app - copie » :
FastAPI + React, mécanique relationnelle **100 % déterministe côté serveur**
(le LLM n'incarne que le personnage — il ne calcule ni score, ni stades,
ni scénarios, ni photos).

## Architecture

```
client/          React 18 + TS + Vite 6 + Tailwind v4 (build → server/static)
server/
  main.py        FastAPI : REST + WebSocket chat + statique
  config.py      Chargement YAML (config/config.yaml)
  relation/      Score, stades, scénarios, presets, souvenirs (déterministe)
  llm/           Client llama.cpp (streaming SSE) + prompt builder
  image/         ComfyUI : portrait auto + photos gated par stade
  prompts/       Persona du compagnon (SystemPrompt_Compagnon.md)
data/
  character_presets/   25 personnages + 275 scénarios (portés de l'original)
server/data/     Runtime : sessions, historiques, photos, users.json
config/          config.yaml (local, gitignoré) — voir config.example.yaml
```

## Mécanique (indépendante du LLM)

- **Score relationnel** (100 au départ) ajusté après chaque message par un
  moteur mots-clés/patterns ; stades : rejet → froid → réservé → neutre →
  chaleureux → proche.
- **Scénarios** (lettres A-K par personnage) injectés côté serveur selon les
  gates de stade ; consommation détectée par similarité cosinus entre le
  scénario et la réponse (embeddings llamaembed), forcée après 3 tours.
- **Décroissance temporelle** après 3 jours d'absence (-10 pts/jour, plafond -150).
- **Souvenirs** : extraction périodique (tous les 10 tours) + rappel sémantique top-k.
- **Photos** : portrait généré automatiquement à la création de session ;
  demandes via bouton 📷 (refusées avant le stade « neutre », tenue contrainte
  par stade).
- **VRAM** : le modèle de chat est déchargé quand aucun tour n'est actif,
  libérant la place pour ComfyUI.

## Démarrage (Docker, recommandé)

Prérequis : les conteneurs `llamacpp` (chat) et `llamaembed` (embeddings)
tournent sur le réseau `openwebui-net` — démarrés via le docker-compose du
projet « d&d app - copie » :

```powershell
cd "..\d&d app - copie"
docker compose up -d llamacpp llamaembed
cd "..\Ami(e) IA app"
.\scripts\demarrer-serveur.bat     # docker compose up -d --build
# → http://localhost:8124
.\scripts\arreter-serveur.bat      # arrêt
```

ComfyUI doit tourner sur l'hôte (port 8188) pour les images.

## Développement local

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn server.main:app --port 8000

cd client
npm install
npm run dev          # http://localhost:5174 (proxy /api /ws /data → 8000)
npm run build        # → ../server/static
```

En local, adapter `config/config.yaml` : `llm.base_url: http://127.0.0.1:8080/v1`
et `memory.embedding_base_url: http://127.0.0.1:8081/v1`.

## Configuration

Copier `config.example.yaml` vers `config/config.yaml` puis ajuster :
backend LLM (`llamacpp`/`ollama`), modèle, paramètres relationnels
(cooldown des scénarios, décroissance, seuils de similarité…).

## API

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/health` | État des backends |
| POST | `/api/login` | Connexion/création compte (`{nom, mot_de_passe}`) |
| GET | `/api/presets` | Personnages prédéfinis |
| GET/POST | `/api/sessions` | Liste / création de rencontre |
| GET/DELETE | `/api/sessions/{id}` | Profil public / suppression |
| GET | `/api/sessions/{id}/photos` | Album photo |
| WS | `/ws/{id}` | Chat : `join` / `say` / `photo_request` |

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```
