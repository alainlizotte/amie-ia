# 💕 Ami(e) IA — Rencontres virtuelles

> **⚠️ Contenu pour adultes averti (18 ans +)** — Cette application simule des
> relations virtuelles et peut générer des contenus sensibles à mesure que la
> relation évolue. Une déclaration de majorité est demandée à la connexion.

Application de **simulation de rencontre** avec des personnages IA : vous
discutez avec un personnage, vos mots font évoluer la relation, et vous
découvrez peu à peu son histoire — jusqu'à décrocher des photos et atteindre
une relation « proche ».

Le tout tourne **en local sur votre machine** (aucune donnée envoyée sur
Internet) : chat sous llama.cpp, images sous ComfyUI, mémoire vectorielle
sous un serveur d'embeddings.

---

## 🎯 Le but du jeu

Chaque rencontre démarre au stade **« froid »** (score 100/1000) :

```
rejet → froid → réservé → neutre → chaleureux → proche
```

- **Discutez** avec le personnage : chaque message est analysé par un moteur
  déterministe qui ajuste le score relationnel (+/- points selon la
  gentillesse, l'intérêt porté, les impairs…).
- **Faites monter la relation** : franchir un stade débloque de nouveaux
  scénarios narratifs et le droit de demander des 📷 **photos**
  (refusées avant le stade « neutre »).
- **Vivez les scénarios** : le serveur injecte périodiquement des événements
  scriptés (rendez-vous, surprises, crises…) selon votre stade — au total
  **275 scénarios** répartis sur les personnages.
- **Entretenez le lien** : après 3 jours sans nouvelles, la relation se
  dégrade (-10 pts/jour). Les absents sont punis !
- **Objectif** : atteindre le stade « proche »… et y rester.

## ✨ Fonctionnalités

| | |
|---|---|
| 💬 **Chat en temps réel** | WebSocket, réponses streaming du personnage, indicateur de saisie |
| 🎭 **25 personnages** | Personnages prédéfinis (apparence, caractère, histoire) ou création personnalisée |
| ❤️ **Relation chiffrée** | Score /1000 + stades affichés, évolution visible après chaque message |
| 📸 **Album photo** | Portrait généré automatiquement à la rencontre, photos supplémentaires à débloquer |
| 🔒 **Garde-fous techniques** | Tenue des photos contrainte par stade côté serveur — le LLM ne peut pas contourner |
| 🧠 **Mémoire** | Extraction périodique de souvenirs + rappel sémantique (le personnage se souvient de vous) |
| 👤 **Comptes locaux** | Chaque utilisateur voit uniquement ses sessions |
| 🖼 **Visionneuse** | Album consultable plein écran (clavier ←/→, Échap) |

## 🖼 Captures d'écran

| | |
|---|---|
| ![Écran de connexion](screenshots/ecran_connection.png) | ![Sélection de session](screenshots/selection_session.png) |
| ![Sélection de personnage](screenshots/sélection_personnage.png) | ![Création de personnage](screenshots/création_personnage.png) |
| ![Conversation principale](screenshots/chat_principal.png) | ![Album photo](screenshots/album_photo.png) |

## ⚙️ Comment ça marche

La particularité d'Ami(e) IA : la mécanique de jeu est **100 % déterministe
et côté serveur**. Le LLM n'incarne QUE le personnage — il ne calcule ni
score, ni stades, ni scénarios, ni photos. Impossible de le convaincre de
« tricher ».

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

### Mécanique détaillée

- **Score relationnel** (100 au départ) ajusté après chaque message par un
  moteur mots-clés/patterns ; stades : rejet → froid → réservé → neutre →
  chaleureux → proche.
- **Scénarios** (lettres A-K par personnage) injectés côté serveur selon les
  gates de stade ; consommation détectée par similarité cosinus entre le
  scénario et la réponse (embeddings), forcée après 3 tours.
- **Décroissance temporelle** après 3 jours d'absence (-10 pts/jour,
  plafond -150).
- **Souvenirs** : extraction périodique (tous les 10 tours) + rappel
  sémantique top-k.
- **Photos** : portrait généré automatiquement à la création de session ;
  demandes via bouton 📷 (refusées avant le stade « neutre », tenue contrainte
  par stade).
- **VRAM** : le modèle de chat est déchargé quand aucun tour n'est actif,
  libérant la place pour ComfyUI.
- **18+** : mention affichée sur l'écran de connexion + case de déclaration
  de majorité obligatoire.

## 🚀 Démarrage (Docker, recommandé)

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

## 🛠 Développement local

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
