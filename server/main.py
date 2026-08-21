"""Point d'entrée FastAPI de l'application Ami(e) IA — serveur dédié.

Architecture identique au projet D&D 3.5 (« d&d app - copie ») :
- FastAPI + WebSocket pour le chat temps réel ;
- LLM local via llama.cpp (endpoint OpenAI-compatible) — réutilisé du projet D&D ;
- embeddings via llamaembed (souvenirs sémantiques) — réutilisé du projet D&D ;
- images via ComfyUI (portraits et photos de session) ;
- mécanique relationnelle 100 % déterministe côté serveur (server/relation/).

Le LLM n'appelle AUCUN outil : il incarne uniquement le personnage. Score,
stades, scénarios, photos et souvenirs sont gérés par le serveur.

Endpoints REST :
- GET  /api/health              → état des backends (llm, embeddings, images)
- POST /api/login               → crée/vérifie un utilisateur (SHA-256)
- GET  /api/presets             → personnages prédéfinis (pour le GUI)
- GET  /api/sessions            → sessions d'un utilisateur
- POST /api/sessions            → crée une session (+ génération du portrait)
- GET  /api/sessions/{id}       → profil public d'une session
- DELETE /api/sessions/{id}     → supprime la session et ses photos
- GET  /api/sessions/{id}/photos → album photo de la session
- WS   /ws/{id}                 → canal chat (join/say/photo_request)

Au WS, format des messages reçus :
    {"type": "join", "user": "alain", "password": "…"}
    {"type": "say", "text": "salut!"}
    {"type": "photo_request", "hint": "au café"}
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import AppConfig, get_config
from .image import helpers as img_helpers
from .llm.client import LLMClient, Message
from .llm.prompt_builder import PromptBuilder
from .relation import presets as P
from .relation.memory import (
    EXTRACTION_PROMPT,
    Embedder,
    MemoryStore,
    cosine,
    parse_facts,
)
from .relation.scoring import apply_time_decay, compute_delta
from .relation.state import RelationState
from .relation.stages import compute_stage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
_log = logging.getLogger("amie.main")


# --------------------------------------------------------------------------- #
#  Lifespan : initialise les clients singleton, dispose proprement.
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    app.state.cfg = cfg

    # Client LLM (llama.cpp réutilisé du projet D&D).
    client = LLMClient(cfg.llm)
    available = await client.list_models()
    model_names = [m.get("id", "") for m in available]
    if available and cfg.llm.model not in model_names:
        print(
            f"[amie] ATTENTION Modele '{cfg.llm.model}' absent du backend "
            f"(disponibles : {', '.join(model_names)})."
        )
    else:
        print(f"[amie] Backend LLM OK : {cfg.llm.base_url} / {cfg.llm.model}")
    app.state.client = client
    app.state.prompt_builder = PromptBuilder(cfg)

    # Embedder (llamaembed réutilisé du projet D&D) — souvenirs sémantiques.
    embedder: Optional[Embedder] = None
    if cfg.memory.enabled:
        embedder = Embedder(
            base_url=cfg.memory.embedding_base_url,
            model=cfg.memory.embedding_model,
        )
        if not await embedder.available():
            print(
                f"[amie] ATTENTION Serveur d'embeddings injoignable sur "
                f"'{cfg.memory.embedding_base_url}' - souvenirs en mode degrade."
            )
        else:
            print(f"[amie] Embeddings OK : {cfg.memory.embedding_base_url}")
    app.state.embedder = embedder
    app.state.memories = MemoryStore(embedder, max_memories=cfg.relation.max_memories)

    # Backend ComfyUI (images).
    app.state.image = (
        img_helpers.get_backend(cfg.image.base_url, cfg.image.timeout_total)
        if cfg.image.enabled else None
    )
    if app.state.image is not None:
        ok = await app.state.image.dispo()
        print(f"[amie] ComfyUI {'OK' if ok else 'injoignable'} : {app.state.image.base_url}")

    print("[amie] Démarrage terminé.")
    yield

    await client.aclose()
    if embedder is not None:
        await embedder.aclose()
    if app.state.image is not None:
        await app.state.image.aclose()
    print("[amie] Arrêt propre terminé.")


app = FastAPI(title="Ami(e) IA — Simulation de rencontre", lifespan=lifespan)

cfg = get_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
#  Utilisateurs — data/users.json (hash SHA-256, jamais en clair)
# --------------------------------------------------------------------------- #
def _users_path() -> Path:
    return cfg.abs(cfg.paths.data_dir) / "users.json"


def _load_users() -> dict[str, Any]:
    path = _users_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"users": {}}


def _save_users(users: dict[str, Any]) -> None:
    path = _users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _hash_password(mdp: str) -> str:
    return hashlib.sha256(mdp.encode("utf-8")).hexdigest()


def _verify_user(nom: str, mot_de_passe: str) -> bool:
    users = _load_users()
    entry = users.get("users", {}).get(nom.strip().lower())
    if not entry:
        return False
    return entry.get("password_sha256") == _hash_password(mot_de_passe)


def _register_user(nom: str, mot_de_passe: str) -> bool:
    """Crée l'utilisateur. Renvoie False si le nom est déjà pris."""
    users = _load_users()
    key = nom.strip().lower()
    if key in users.get("users", {}):
        return False
    users.setdefault("users", {})[key] = {
        "nom": nom.strip(),
        "password_sha256": _hash_password(mot_de_passe),
        "created": datetime.now().isoformat(),
    }
    _save_users(users)
    return True


# --------------------------------------------------------------------------- #
#  Sessions — helpers
# --------------------------------------------------------------------------- #
def _state(sid: str) -> RelationState:
    return RelationState(str(cfg.abs(cfg.paths.data_dir)), sid)


def _own_session(sid: str, user: str) -> dict[str, Any]:
    """Charge le profil et vérifie l'appartenance (404 sinon — pas 403,
    pour ne pas révéler l'existence des sessions d'autrui)."""
    st = _state(sid)
    if not st.exists():
        raise HTTPException(status_code=404, detail="Session introuvable.")
    profile = st.load()
    owner = (profile.get("meta", {}) or {}).get("user", "")
    if "_erreur" in profile or owner != (user or "").strip().lower():
        raise HTTPException(status_code=404, detail="Session introuvable.")
    return profile


def _public_profile(st: RelationState, profile: dict[str, Any]) -> dict[str, Any]:
    """Vue « publique » du profil envoyée au GUI."""
    character = profile.get("character", {}) or {}
    photos = profile.get("photos", []) or []
    portrait = next((p for p in photos if p.get("kind") == "portrait"), None)
    preset_id = character.get("preset_id")
    total_events = len(P.get_events_for_character(preset_id)) if preset_id else 0
    return {
        "session_id": profile.get("meta", {}).get("session_id", ""),
        "titre": profile.get("meta", {}).get("titre", ""),
        "character": {
            "name": character.get("name", ""),
            "age": character.get("age", ""),
            "title": character.get("title", ""),
            "gender": character.get("gender", ""),
            "occupation": character.get("occupation", ""),
            "interests": character.get("interests", ""),
            "appearance": character.get("appearance", ""),
            "personality": character.get("personality", ""),
            "preset_id": preset_id,
        },
        "user_info": profile.get("user_info", {}),
        "score": profile.get("relationship_score", 100),
        "stage": profile.get("relationship_stage", "froid"),
        "interaction_count": profile.get("interaction_count", 0),
        "last_interaction": profile.get("last_interaction"),
        "portrait_url": st.photo_url(portrait["file"]) if portrait else None,
        "photos_count": len(photos),
        "events_consumed": len(profile.get("event_history", []) or []),
        "events_total": total_events,
        "date_creation": profile.get("meta", {}).get("date_creation", ""),
    }


def _chat_path(sid: str) -> Path:
    return cfg.abs(cfg.paths.data_dir) / f"chat_{sid}.json"


class ChatHistory:
    """Historique conversationnel persistant par session (atomique)."""

    def __init__(self, sid: str, max_events: int = 60):
        self.sid = sid
        self.max_events = max_events
        self.history: list[Message] = []
        self._hydrate()

    def _hydrate(self) -> None:
        path = _chat_path(self.sid)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.history = [
                Message(role=d.get("role", "user"), content=d.get("content", ""))
                for d in data
                if isinstance(d, dict)
            ][-self.max_events:]
        except (OSError, json.JSONDecodeError):
            self.history = []

    def append(self, role: str, content: str) -> None:
        if not content:
            return
        self.history.append(Message(role=role, content=content))
        if len(self.history) > self.max_events:
            self.history = self.history[-self.max_events:]
        self._persist()

    def _persist(self) -> None:
        path = _chat_path(self.sid)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    [{"role": m.role, "content": m.content} for m in self.history],
                    f, ensure_ascii=False, indent=2,
                )
            tmp.replace(path)
        except OSError:
            pass


class SessionHub:
    """Connexions WS actives d'une session + verrou de tour."""

    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()
        self.turn_lock = asyncio.Lock()

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.discard(ws)


_hubs: dict[str, SessionHub] = {}


def _hub(sid: str) -> SessionHub:
    if sid not in _hubs:
        _hubs[sid] = SessionHub()
    return _hubs[sid]


# --------------------------------------------------------------------------- #
#  Compteur global de tours actifs (déchargement VRAM quand zéro tour).
# --------------------------------------------------------------------------- #
_active_turns: int = 0
_turns_guard = asyncio.Lock()


async def _turn_begin() -> None:
    global _active_turns
    async with _turns_guard:
        _active_turns += 1


async def _turn_end() -> bool:
    global _active_turns
    async with _turns_guard:
        _active_turns = max(0, _active_turns - 1)
        return _active_turns == 0


# --------------------------------------------------------------------------- #
#  Routes REST
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health() -> dict[str, Any]:
    try:
        models = await app.state.client.list_models()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)
    embedder: Optional[Embedder] = getattr(app.state, "embedder", None)
    image = getattr(app.state, "image", None)
    return {
        "ok": True,
        "backend": cfg.llm.backend,
        "backend_url": cfg.llm.base_url,
        "model": cfg.llm.model,
        "model_available": any(
            cfg.llm.model in m.get("id", "") for m in models
        ),
        "memory_enabled": embedder is not None,
        "image_available": bool(image) and await image.dispo(),
        "presets_loaded": len(P.load_preset_characters()),
    }


@app.post("/api/login")
async def login(payload: dict[str, Any]) -> dict[str, Any]:
    """Connexion. Crée le compte s'il n'existe pas encore."""
    nom = (payload.get("nom") or "").strip()
    mdp = payload.get("mot_de_passe") or ""
    if not nom or not mdp:
        raise HTTPException(status_code=400, detail="Nom et mot de passe requis.")
    if len(mdp) < 4:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (4 caractères min).")
    users = _load_users().get("users", {})
    exists = nom.lower() in users
    if exists:
        if not _verify_user(nom, mdp):
            raise HTTPException(status_code=401, detail="Mot de passe incorrect.")
        nouveau = False
    else:
        if not _register_user(nom, mdp):
            raise HTTPException(status_code=409, detail="Ce nom est déjà pris.")
        nouveau = True
    return {"ok": True, "user": nom.strip(), "nouveau": nouveau}


@app.get("/api/presets")
async def list_presets() -> dict[str, Any]:
    """Personnages prédéfinis (infos légères pour le GUI de création)."""
    chars = [
        {
            "id": c.get("id", ""),
            "name": c.get("name", ""),
            "age": c.get("age", ""),
            "title": c.get("title", ""),
            "gender": c.get("gender", ""),
            "personality": c.get("personality", ""),
            "occupation": (c.get("parcours", {}) or {}).get("professionnel", ""),
        }
        for c in P.load_preset_characters()
    ]
    return {"characters": chars}


@app.get("/api/sessions")
async def list_sessions(user: str = "") -> dict[str, Any]:
    """Liste des sessions créées par un utilisateur."""
    user_key = (user or "").strip().lower()
    if not user_key:
        raise HTTPException(status_code=400, detail="Paramètre 'user' requis.")
    data_dir = cfg.abs(cfg.paths.data_dir)
    sessions_out: list[dict[str, Any]] = []
    for p in sorted(data_dir.glob("session_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        sid = p.stem[len("session_"):]
        st = _state(sid)
        profile = st.load()
        if "_erreur" in profile:
            continue
        if (profile.get("meta", {}) or {}).get("user", "") != user_key:
            continue
        pub = _public_profile(st, profile)
        pub["last_message"] = _last_chat_message(sid)
        sessions_out.append(pub)
    return {"sessions": sessions_out}


def _last_chat_message(sid: str) -> str:
    try:
        with open(_chat_path(sid), "r", encoding="utf-8") as f:
            data = json.load(f)
        for d in reversed(data):
            if d.get("role") == "assistant" and d.get("content"):
                return d["content"][:120]
    except (OSError, json.JSONDecodeError):
        pass
    return ""


@app.post("/api/sessions")
async def create_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Crée une session de rencontre.

    Deux modes :
    - `preset_id` : personnage prédéfini (scénarios activés) ;
    - `character` : personnage personnalisé (formulaire GUI — pas de scénarios).
    Le portrait est généré automatiquement en arrière-plan (ComfyUI).
    """
    user = (payload.get("user") or "").strip().lower()
    if not user:
        raise HTTPException(status_code=400, detail="Champ 'user' requis.")

    preset_id = (payload.get("preset_id") or "").strip() or None
    custom = payload.get("character") or {}

    if preset_id:
        preset = P.get_preset_character(preset_id)
        if preset is None:
            raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' introuvable.")
        character = P.build_character_from_preset(preset)
    else:
        name = (custom.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Le nom du personnage est requis.")
        character = {
            "preset_id": None,
            "name": name,
            "age": custom.get("age", ""),
            "title": custom.get("title", ""),
            "gender": (custom.get("gender") or "F").upper()[:1],
            "occupation": custom.get("occupation", ""),
            "interests": custom.get("interests", ""),
            "appearance": custom.get("appearance", ""),
            "personality": custom.get("personality", ""),
            "parcours": {},
            "histoire_personnelle": "",
            "parcours_amoureux": "",
        }

    import uuid
    sid = uuid.uuid4().hex[:10]
    st = _state(sid)
    profile = st.load()
    profile["meta"].update({
        "user": user,
        "session_id": sid,
        "titre": character.get("name", "Rencontre"),
        "date_creation": datetime.now().isoformat(),
    })
    profile["character"] = character
    ui = payload.get("user_info") or {}
    profile["user_info"] = {
        "name": (ui.get("name") or "").strip(),
        "preferences": (ui.get("preferences") or "").strip(),
    }
    err = st.save(profile)
    if err:
        raise HTTPException(status_code=500, detail=err)

    # Génération du portrait en arrière-plan (le GUI interroge ensuite
    # GET /api/sessions/{id} jusqu'à ce que portrait_url apparaisse).
    asyncio.create_task(_generate_portrait(sid))

    return {"ok": True, "session_id": sid, "profile": _public_profile(st, profile)}


@app.get("/api/sessions/{sid}")
async def get_session(sid: str, user: str = "") -> dict[str, Any]:
    profile = _own_session(sid, user)
    return _public_profile(_state(sid), profile)


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str, user: str = "") -> dict[str, Any]:
    _own_session(sid, user)
    _state(sid).delete()
    try:
        _chat_path(sid).unlink()
    except OSError:
        pass
    return {"ok": True}


@app.get("/api/sessions/{sid}/photos")
async def session_photos(sid: str, user: str = "") -> dict[str, Any]:
    profile = _own_session(sid, user)
    st = _state(sid)
    photos = [
        {
            "url": st.photo_url(p.get("file", "")),
            "kind": p.get("kind", "photo"),
            "caption": p.get("caption", ""),
            "ts": p.get("ts", ""),
        }
        for p in reversed(profile.get("photos", []) or [])
    ]
    return {"photos": photos}


# --------------------------------------------------------------------------- #
#  Génération d'images (portrait à la création + photos demandées)
# --------------------------------------------------------------------------- #
async def _generate_portrait(sid: str) -> None:
    """Génère la photo de référence du personnage (arrière-plan, sans LLM).

    Sérialisée sur hub.turn_lock : sans cela, un tour de chat concurrent
    sauvegarderait sa copie du profil et écraserait la photo ajoutée.
    """
    image = getattr(app.state, "image", None)
    st = _state(sid)
    hub = _hub(sid)
    async with hub.turn_lock:
        profile = st.load()
        if "_erreur" in profile or image is None:
            return
        character = profile.get("character", {})
        prompt = img_helpers.portrait_prompt(character)
        dest_dir = st.photos_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "portrait.png"
        await hub.broadcast({
            "type": "tool_event",
            "event": {"type": "image_pending", "msg": img_helpers.MSG_PENDING_PORTRAIT},
        })
        path = await img_helpers.generer_image(image, "portrait", prompt, str(dest))
        if path is None:
            _log.warning("[portrait] échec génération pour %s (voir logs image)", sid)
            await hub.broadcast({
                "type": "tool_event",
                "event": {"type": "error", "msg": "⚠️ Génération du portrait impossible (ComfyUI injoignable ?)."},
            })
            return
        profile = st.load()
        st.add_photo(profile, dest.name, "portrait",
                     img_helpers.caption_for("portrait", "", character.get("name", "")))
        st.save(profile)
        await hub.broadcast({
            "type": "tool_event",
            "event": {
                "type": "image_ready",
                "kind": "portrait",
                "msg": "📸 Photo de profil prête !",
                "image": st.photo_url(dest.name),
                "caption": img_helpers.caption_for("portrait", "", character.get("name", "")),
            },
        })


async def _scene_de_la_conversation(sid: str, character: dict[str, Any],
                                    stage: str, user_request: str = "") -> str:
    """Fragments visuels de la scène en cours, dérivés des derniers échanges.

    Un appel LLM court (« directeur photo ») transforme la fin de la
    conversation en description d'image (30 mots max), sanitizée selon le
    stade. `user_request` : demande explicite saisie au moment du 📷 — elle
    prime si le personnage l'a acceptée. En cas d'échec/timeout : "" — le
    prompt retombe sur la fiche du personnage seule (jamais bloquant).
    """
    llm = getattr(app.state, "client", None)
    if llm is None:
        return ""
    try:
        hist = [m for m in ChatHistory(sid).history
                if m.role in ("user", "assistant")][-8:]
        if not hist and not user_request:
            return ""
        nom = character.get("name") or "character"
        transcript = "\n".join(
            f"{'user' if m.role == 'user' else nom}: {m.content[:280]}"
            for m in hist
        )
        msgs = [
            Message(role="system",
                    content=img_helpers.director_system(
                        character, stage, user_request)),
            Message(role="user", content=transcript or "(no conversation yet)"),
        ]
        async with asyncio.timeout(45):
            res = await llm.chat(msgs, temperature=0.3)
    except Exception as e:
        _log.warning("[photo] directeur photo indisponible (%s) — "
                     "prompt déterministe seul", e)
        return ""
    scene = img_helpers.sanitize_scene(res.content, stage)
    if scene:
        _log.info("[photo] scène détectée : %s", scene)
    return scene


async def _handle_photo_request(hub: SessionHub, sid: str, hint: str) -> None:
    """Traite une demande de photo — décision 100 % côté serveur.

    Sérialisée sur hub.turn_lock (même raison que _generate_portrait :
    éviter qu'un tour concurrent écrase l'ajout de la photo au profil).

    Gate par stade (refus déterministe sans LLM sous « neutre »), prompt
    construit depuis la fiche du personnage avec contraintes de tenue selon
    le stade, génération ComfyUI, enregistrement dans l'album.
    """
    image = getattr(app.state, "image", None)
    st = _state(sid)
    async with hub.turn_lock:
        profile = st.load()
        if "_erreur" in profile:
            return
        stage = profile.get("relationship_stage", "froid")

        refusal = img_helpers.REFUSALS_BY_STAGE.get(stage)
        if refusal:
            await hub.broadcast({
                "type": "tool_event",
                "event": {"type": "info", "msg": refusal},
            })
            return
        if image is None:
            await hub.broadcast({
                "type": "tool_event",
                "event": {"type": "error", "msg": "⚠️ Génération d'images désactivée."},
            })
            return

        # Annonce IMMÉDIATE (avant le directeur photo et la génération) :
        # l'utilisateur doit voir l'indication dès son appui sur 📷.
        await hub.broadcast({
            "type": "tool_event",
            "event": {"type": "image_pending", "msg": img_helpers.MSG_PENDING_PHOTO},
        })

        character = profile.get("character", {})
        scene = await _scene_de_la_conversation(sid, character, stage,
                                                hint or "")
        prompt = img_helpers.photo_prompt_for_stage(
            character, stage, hint or "", scene,
        )
        _log.info("[photo] prompt : %s", prompt)
        dest_dir = st.photos_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        fname = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        dest = dest_dir / fname

        path = await img_helpers.generer_image(image, "photo", prompt, str(dest))
        if path is None:
            await hub.broadcast({
                "type": "tool_event",
                "event": {"type": "error", "msg": "⚠️ La génération de la photo a échoué."},
            })
            return

        profile = st.load()
        caption = img_helpers.caption_for("photo", stage, character.get("name", ""))
        st.add_photo(profile, fname, "photo", caption)
        st.save(profile)
        await hub.broadcast({
            "type": "tool_event",
            "event": {
                "type": "image_ready",
                "kind": "photo",
                "msg": "📸 Nouvelle photo !",
                "image": st.photo_url(fname),
                "caption": caption,
            },
        })


# --------------------------------------------------------------------------- #
#  Tour de conversation — pipeline déterministe
# --------------------------------------------------------------------------- #
async def _extract_memories_if_due(
    sid: str, profile: dict[str, Any], user_text: str, narration: str
) -> None:
    """Extraction périodique de souvenirs (appel LLM secondaire, défensif).

    Un échec (JSON invalide, modèle injoignable) n'a AUCUN impact sur la
    conversation — les souvenirs restent simplement inchangés.
    """
    cfg_ = app.state.cfg
    every = max(1, int(cfg_.relation.summarize_every_turns))
    count = int(profile.get("interaction_count", 0) or 0)
    if count % every != 0:
        return
    try:
        result = await app.state.client.chat(
            [Message(
                role="user",
                content=(
                    EXTRACTION_PROMPT
                    + f"UTILISATEUR : {user_text[:1500]}\n"
                    + f"PERSONNAGE : {narration[:1500]}"
                ),
            )],
            temperature=0.0,
        )
        facts = parse_facts(result.content)
        if facts:
            added = await app.state.memories.add_facts(profile, facts)
            if added:
                _log.info("[%s] %d souvenir(s) ajouté(s)", sid, added)
    except Exception as e:                                   # noqa: BLE001
        _log.warning("[%s] extraction de souvenirs échouée (ignorée) : %s", sid, e)


async def _handle_say(hub: SessionHub, sid: str, text: str) -> None:
    """Pipeline complet d'un tour — aucune intervention du LLM dans la mécanique."""
    if not text.strip():
        return
    rcfg = cfg.relation
    st = _state(sid)
    hub_hist = ChatHistory(sid)  # léger : hydrate depuis le disque

    # 1. Mémorise + echo du message utilisateur.
    hub_hist.append("user", text.strip())
    await hub.broadcast({"type": "player", "text": text})
    await hub.broadcast({"type": "status", "description": f"écrit…"})
    await hub.broadcast({"type": "typing", "on": True})

    await _turn_begin()
    try:
        async with hub.turn_lock:
            profile = st.load()
            if "_erreur" in profile:
                await hub.broadcast({"type": "dm", "text": "⚠️ Profil illisible."})
                return

            # 2. Décroissance temporelle si reprise après plusieurs jours.
            now = datetime.utcnow()
            score = int(profile.get("relationship_score", rcfg.default_score))
            new_score, decayed = apply_time_decay(
                score, profile.get("last_interaction"), now,
                days_grace=rcfg.decay_days_grace,
                points_per_day=rcfg.decay_points_per_day,
                max_loss=rcfg.decay_max_loss,
            )
            if decayed:
                st.set_score(profile, new_score, mark_interaction=False)

            stage = compute_stage(int(profile["relationship_score"]))

            # 3. Scénario en attente (gates par stade déjà appliquées).
            pending = P.get_pending_event(profile, stage, cooldown_hours=rcfg.cooldown_hours)
            if pending:
                profile["last_injected_event_id"] = pending.get("event_id")

            # 4. Souvenirs rappelés (recherche sémantique llamaembed).
            memories = []
            if app.state.memories is not None:
                try:
                    memories = await app.state.memories.retrieve(
                        profile, text,
                        top_k=cfg.memory.top_k,
                        min_similarity=cfg.memory.min_similarity,
                    )
                except Exception as e:                           # noqa: BLE001
                    _log.warning("rappel de souvenirs échoué (ignoré) : %s", e)

            # 5. Prompt système complet + historique.
            system_text = app.state.prompt_builder.build_system_message(
                profile, memories, pending
            )
            messages = [Message(role="system", content=system_text)] + list(hub_hist.history)

            # 6. Génération en streaming (aucun tool exposé au modèle).
            narration_parts: list[str] = []
            async for token in app.state.client.stream_chat(messages):
                narration_parts.append(token)
                await hub.broadcast({"type": "delta", "text": token})
            narration = "".join(narration_parts).strip()
            if not narration:
                narration = "…"  # garde-fou : jamais de bulle vide

            hub_hist.append("assistant", narration)
            await hub.broadcast({"type": "dm", "text": narration})

            # 7. Auto-scoring déterministe (mots-clés + patterns).
            delta = compute_delta(
                text, narration, stage,
                delta_max=rcfg.delta_max, delta_min=rcfg.delta_min,
            )
            old_stage = stage
            st.set_score(
                profile,
                int(profile["relationship_score"]) + delta,
                mark_interaction=True,
            )
            new_stage = profile["relationship_stage"]

            # 8. Consommation du scénario injecté — similarité cosinus entre
            #    le corps de l'event et la réponse (embeddings llamaembed),
            #    avec consommation forcée après event_max_attempts tours.
            consumed_now = False
            if pending:
                eid = pending.get("event_id", "")
                attempts_map = profile.setdefault("event_attempts", {})
                attempts = int(attempts_map.get(eid, 0)) + 1
                sim = 0.0
                embedder: Optional[Embedder] = getattr(app.state, "embedder", None)
                if embedder is not None:
                    try:
                        ev_vec = await embedder.embed_documents([pending.get("body", "")])
                        as_vec = await embedder.embed_query(narration[:2000])
                        sim = cosine(ev_vec[0], as_vec)
                    except Exception:
                        sim = 0.0
                else:
                    sim = rcfg.event_consume_similarity  # mode dégradé : consomme
                if sim >= rcfg.event_consume_similarity or attempts >= rcfg.event_max_attempts:
                    P.mark_event_consumed(profile, eid)
                    consumed_now = True
                else:
                    attempts_map[eid] = attempts
                    profile["last_injected_event_id"] = None  # retenter plus tard

            st.save(profile)

            # 9. Extraction périodique de souvenirs (tous les N tours).
            await _extract_memories_if_due(sid, profile, text, narration)

            # 10. Diffuse l'état relationnel mis à jour (barre de progression GUI).
            await hub.broadcast({
                "type": "profile",
                "score": profile["relationship_score"],
                "stage": new_stage,
                "stage_changed": new_stage != old_stage,
                "delta": delta,
                "interaction_count": profile.get("interaction_count", 0),
                "events_consumed": len(profile.get("event_history", []) or []),
                "event_consumed_now": consumed_now,
            })
    except Exception as e:                                   # noqa: BLE001
        print(f"[amie] Tour échoué ({sid}) : {e}")
        await hub.broadcast({
            "type": "dm",
            "text": "⚠️ Un problème technique est survenu. Réessaie dans un instant.",
        })
    finally:
        last_turn = await _turn_end()

    await hub.broadcast({"type": "typing", "on": False})
    await hub.broadcast({"type": "status", "description": "", "done": True})

    # 11. Décharge le modèle de la VRAM si plus aucun tour actif
    #     (libère la place pour ComfyUI — même chorégraphie que le projet D&D).
    if last_turn:
        try:
            await app.state.client.unload_model()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  WebSocket : canal chat d'une session
# --------------------------------------------------------------------------- #
@app.websocket("/ws/{sid}")
async def ws_chat(ws: WebSocket, sid: str) -> None:
    await ws.accept()
    hub = _hub(sid)
    authenticated = False
    user = ""

    # Vérifie d'emblée que la session existe (sans rien révéler sinon).
    st = _state(sid)
    if not st.exists():
        await ws.send_json({"type": "sys", "event": "error", "detail": "Session introuvable."})
        await ws.close()
        return
    profile = st.load()
    if "_erreur" in profile:
        await ws.send_json({"type": "sys", "event": "error", "detail": "Session illisible."})
        await ws.close()
        return

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "sys", "event": "error", "detail": "payload non JSON"})
                continue

            mtype = msg.get("type")

            if mtype == "join":
                user = (msg.get("user") or "").strip()
                password = msg.get("password") or ""
                if not user or not _verify_user(user, password):
                    await ws.send_json({
                        "type": "sys", "event": "auth_failed",
                        "detail": "Nom ou mot de passe incorrect.",
                    })
                    continue
                if (profile.get("meta", {}) or {}).get("user", "") != user.lower():
                    await ws.send_json({
                        "type": "sys", "event": "auth_failed",
                        "detail": "Cette session n'appartient pas à cet utilisateur.",
                    })
                    continue
                authenticated = True
                hub.connections.add(ws)
                hist = ChatHistory(sid)
                await ws.send_json({
                    "type": "sys",
                    "event": "joined",
                    "history": [
                        {"role": m.role, "content": m.content}
                        for m in hist.history
                        if m.role in ("user", "assistant") and m.content
                    ],
                    "profile": _public_profile(_state(sid), profile),
                })
                continue

            if not authenticated:
                await ws.send_json({
                    "type": "sys", "event": "auth_required",
                    "detail": "Rejoins la session d'abord (join).",
                })
                continue

            if mtype == "say":
                await _handle_say(hub, sid, msg.get("text", ""))
                continue

            if mtype == "photo_request":
                await _handle_photo_request(hub, sid, msg.get("hint", ""))
                continue

            await ws.send_json({"type": "sys", "event": "error",
                                "detail": f"type inconnu: {mtype}"})
    # RuntimeError : déconnexion du client pendant la fenêtre d'ouverture
    # (receive_text appelé alors que le socket n'est plus/ pas encore CONNECTED).
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.connections.discard(ws)


# --------------------------------------------------------------------------- #
#  Frontend statique + montage /data (photos générées)
# --------------------------------------------------------------------------- #
_static = Path(__file__).resolve().parent / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

_data_dir = cfg.abs(cfg.paths.data_dir)
if _data_dir.is_dir():
    app.mount("/data", StaticFiles(directory=str(_data_dir)), name="data")


@app.get("/")
async def index() -> FileResponse:
    path = _static / "index.html"
    if not path.is_file():
        return JSONResponse(
            {"detail": "static/index.html manquant — lancez `npm run build` dans client/."},
            status_code=404,
        )
    return FileResponse(str(path))


@app.get("/{full_path:path}", response_model=None)
async def spa_fallback(full_path: str) -> FileResponse | JSONResponse:
    reserved = ("api", "ws", "data", "static", "docs", "redoc", "openapi.json")
    if full_path.startswith(reserved) or not full_path:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    candidate = _static / full_path
    if candidate.is_file() and ".." not in full_path:
        return FileResponse(str(candidate))
    idx = _static / "index.html"
    if idx.is_file():
        return FileResponse(str(idx))
    return JSONResponse({"detail": "Not Found"}, status_code=404)
