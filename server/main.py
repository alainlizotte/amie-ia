"""Point d'entrée FastAPI de l'application Ami(e) IA — serveur dédié.

Architecture :
- FastAPI + WebSocket pour le chat temps réel ;
- auth par comptes locaux + tokens Bearer HMAC (server/auth.py) ;
- LLM local via llama.cpp (endpoint OpenAI-compatible) ;
- embeddings via llamaembed (souvenirs sémantiques) ;
- images via ComfyUI (portraits et photos de session) ;
- mécanique relationnelle 100 % déterministe côté serveur (server/relation/) ;
- messages proactifs : le personnage écrit le premier après 24 h de silence
  (1 par jour max) ; sans réponse avant le message suivant → -50 points.

Le LLM n'appelle AUCUN outil : il incarne uniquement le personnage. Score,
stades, scénarios, photos et souvenirs sont gérés par le serveur.

Endpoints REST :
- GET  /api/health              → état des backends (llm, embeddings, images)
- POST /api/auth/inscription    → crée un compte (PBKDF2) et renvoie un token
- POST /api/auth/connexion      → connecte un compte existant → token Bearer
- GET  /api/auth/moi            → identité du porteur du token
- GET  /api/presets             → personnages prédéfinis (pour le GUI)
- GET  /api/sessions            → sessions de l'utilisateur (auth requise)
- POST /api/sessions            → crée une session (+ génération du portrait)
- GET  /api/sessions/{id}       → profil public d'une session
- DELETE /api/sessions/{id}     → supprime la session et ses photos
- GET  /api/sessions/{id}/photos → album photo de la session
- WS   /ws/{id}                 → canal chat (join/say/photo_request)

Au WS, format des messages reçus :
    {"type": "join", "token": "nom|exp|sig"}   (token obtenu via /api/auth/*)
    {"type": "say", "text": "salut!"}
    {"type": "photo_request", "hint": "au café"}
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth as auth_mod
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

    # Client LLM (llama.cpp).
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

    # Embedder (llamaembed) — souvenirs sémantiques.
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

    # Boucle des messages proactifs (le personnage écrit après un silence).
    proactive_task: Optional[asyncio.Task] = None
    if cfg.relation.proactive_enabled:
        proactive_task = asyncio.create_task(_proactive_loop())
        print(
            f"[amie] Messages proactifs activés : silence {cfg.relation.proactive_after_hours} h, "
            f"1 max / {cfg.relation.proactive_interval_hours} h, "
            f"pénalité {cfg.relation.proactive_penalty} pts."
        )

    print("[amie] Démarrage terminé.")
    yield

    if proactive_task is not None:
        proactive_task.cancel()
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
#  Authentification — comptes locaux + tokens Bearer (server/auth.py,
#  PBKDF2-SHA256 + HMAC).
# --------------------------------------------------------------------------- #
def _data_dir() -> str:
    return str(cfg.abs(cfg.paths.data_dir))


async def utilisateur_courant(
    authorization: str = Header(default=""),
) -> str:
    """Dépendance FastAPI : renvoie le nom d'utilisateur authentifié ou 401."""
    nom = auth_mod.utilisateur_depuis_header(_data_dir(), authorization)
    if not nom:
        raise HTTPException(status_code=401, detail="Non authentifié.")
    return nom


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
        "unanswered_messages": int(profile.get("unanswered_messages", 0) or 0),
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

    @property
    def busy(self) -> bool:
        """True si un tour est en cours (LLM ou image)."""
        return self.turn_lock.locked()

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
_pending_unload: Optional[asyncio.Task] = None


def _cancel_pending_unload() -> None:
    """Annule un unload différé en attente (un tour reprend la main)."""
    global _pending_unload
    if _pending_unload is not None and not _pending_unload.done():
        _pending_unload.cancel()
    _pending_unload = None


async def _delayed_unload_task(app: FastAPI, delay_s: float) -> None:
    """Décharge le modèle après `delay_s` secondes d'inactivité."""
    global _pending_unload
    try:
        await asyncio.sleep(delay_s)
        async with _turns_guard:
            if _active_turns > 0:
                return  # un tour a repris — il reprogrammera l'unload
            _pending_unload = None
            await app.state.client.unload_model()
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _turn_begin() -> None:
    global _active_turns
    async with _turns_guard:
        _cancel_pending_unload()
        _active_turns += 1


async def _turn_end() -> bool:
    global _active_turns
    async with _turns_guard:
        _active_turns = max(0, _active_turns - 1)
        return _active_turns == 0


async def _turns_idle() -> bool:
    """True si aucun tour actif (pour décharger la VRAM hors tour)."""
    async with _turns_guard:
        return _active_turns == 0


# --------------------------------------------------------------------------- #
#  Déchargement conditionnel du modèle (config llm.unload_after_turn).
# --------------------------------------------------------------------------- #
async def _maybe_unload_model() -> None:
    """Décharge le modèle selon la config :
    - unload_after_turn = true  → immédiat (partage GPU avec ComfyUI).
    - unload_after_turn = false → après unload_delay_minutes d'inactivité
      (annulé si un tour reprend).
    """
    global _pending_unload
    if cfg.llm.unload_after_turn:
        try:
            await app.state.client.unload_model()
        except Exception:
            pass
    else:
        _cancel_pending_unload()
        _pending_unload = asyncio.create_task(
            _delayed_unload_task(app, cfg.llm.unload_delay_minutes * 60)
        )


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


@app.post("/api/auth/inscription")
async def auth_inscription(payload: dict[str, Any]) -> dict[str, Any]:
    """Crée un compte {nom, mot_de_passe} et renvoie directement un token."""
    nom = (payload.get("nom") or "").strip()
    mdp = payload.get("mot_de_passe") or ""
    ok, message = auth_mod.creer_utilisateur(_data_dir(), nom, mdp)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {
        "token": auth_mod.generer_token(_data_dir(), nom),
        "utilisateur": nom,
    }


@app.post("/api/auth/connexion")
async def auth_connexion(payload: dict[str, Any]) -> dict[str, Any]:
    """Connecte un compte existant → token Bearer (migration legacy incluse)."""
    nom = (payload.get("nom") or "").strip()
    mdp = payload.get("mot_de_passe") or ""
    if not auth_mod.verifier_identifiants(_data_dir(), nom, mdp):
        raise HTTPException(status_code=401, detail="Identifiants incorrects.")
    return {
        "token": auth_mod.generer_token(_data_dir(), nom),
        "utilisateur": nom,
    }


@app.get("/api/auth/moi")
async def auth_moi(utilisateur: str = Depends(utilisateur_courant)) -> dict[str, Any]:
    return {"utilisateur": utilisateur}


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
async def list_sessions(
    utilisateur: str = Depends(utilisateur_courant),
) -> dict[str, Any]:
    """Liste des sessions créées par l'utilisateur authentifié."""
    user_key = utilisateur.strip().lower()
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
async def create_session(
    payload: dict[str, Any],
    utilisateur: str = Depends(utilisateur_courant),
) -> dict[str, Any]:
    """Crée une session de rencontre.

    Deux modes :
    - `preset_id` : personnage prédéfini (scénarios activés) ;
    - `character` : personnage personnalisé (formulaire GUI — pas de scénarios).
    Le portrait est généré automatiquement en arrière-plan (ComfyUI).
    """
    user = utilisateur.strip().lower()

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
async def get_session(
    sid: str,
    utilisateur: str = Depends(utilisateur_courant),
) -> dict[str, Any]:
    profile = _own_session(sid, utilisateur)
    return _public_profile(_state(sid), profile)


@app.delete("/api/sessions/{sid}")
async def delete_session(
    sid: str,
    utilisateur: str = Depends(utilisateur_courant),
) -> dict[str, Any]:
    _own_session(sid, utilisateur)
    _state(sid).delete()
    try:
        _chat_path(sid).unlink()
    except OSError:
        pass
    return {"ok": True}


@app.get("/api/sessions/{sid}/photos")
async def session_photos(
    sid: str,
    utilisateur: str = Depends(utilisateur_courant),
) -> dict[str, Any]:
    profile = _own_session(sid, utilisateur)
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
def _preset_portrait_cache(preset_id: str) -> Path | None:
    """Chemin du portrait partagé d'un personnage prédéfini (ou None).

    Le portrait ORIGINAL des presets est généré une seule fois puis réutilisé
    pour toute nouvelle session (tous utilisateurs confondus). Les photos de
    scène et les personnages personnalisés ne participent pas à ce cache.
    """
    clean = re.sub(r"[^A-Za-z0-9_-]", "", str(preset_id)).strip()
    if not clean:
        return None
    return cfg.abs(cfg.paths.data_dir) / "preset_portraits" / f"{clean}.png"


async def _generate_portrait(sid: str) -> None:
    """Génère la photo de référence du personnage (arrière-plan, sans LLM).

    Sérialisée sur hub.turn_lock : sans cela, un tour de chat concurrent
    sauvegarderait sa copie du profil et écraserait la photo ajoutée.
    Si le personnage est un preset dont le portrait original a déjà été
    généré, il est copié depuis le cache sans rappeler ComfyUI.
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

        # Cache partagé : portrait original déjà généré pour ce preset ?
        cache = _preset_portrait_cache(character.get("preset_id") or "")
        from_cache = False
        if cache is not None and cache.is_file():
            try:
                shutil.copyfile(cache, dest)
                from_cache = True
            except OSError:
                from_cache = False  # cache illisible : on régénère normalement

        if not from_cache:
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
            if cache is not None:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(dest, cache)
                except OSError:
                    _log.warning("[portrait] cache non écrit pour %s", cache.name)

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
#  Messages proactifs — le personnage écrit le premier après un silence.
#
#  Règles (config relation.*) :
#  - silence d'au moins `proactive_after_hours` (24 h par défaut) depuis le
#    dernier échange de l'utilisateur (ou la création de la session) ;
#  - au plus un message spontané toutes les `proactive_interval_hours` (1/jour) ;
#  - si l'utilisateur n'a pas répondu au message précédent avant le
#    suivant : -`proactive_penalty` points de relation (50 par défaut) ;
#  - aucun message proactif au stade « rejet » ;
#  - la réponse de l'utilisateur (say) remet le compteur à zéro (badge).
#
#  Gradation émotionnelle : plus les messages restent sans réponse, plus le
#  ton monte — ennui léger → inquiétude → tristesse → frustration → colère
#  blessée. Chaque message spontané exprime le manque de réponse, jamais une
#  simple relance répétée.
# --------------------------------------------------------------------------- #
PROACTIVE_FALLBACKS: dict[str, list[str]] = {
    "froid": [
        "Hey… ça fait un moment. Tu es encore là ?",
        "Hmm, silence radio de ton côté. Tout va bien ?",
        "Coucou, juste un petit coucou pour voir si tu es vivant(e) 😄",
        "Salut ! Longtemps sans nouvelles. Un petit signe de vie ?",
    ],
    "reserve": [
        "Salut ! Je pensais à notre dernière conversation. Ça te dit de reprendre ?",
        "Coucou ! J'espère que ta semaine se passe bien. 🙂",
        "Hey ! Ça fait un bail. Comment tu vas ces temps-ci ?",
        "Tiens, je pensais à toi ce matin. Tout va bien ?",
    ],
    "neutre": [
        "Hey ! Je repensais à ce qu'on s'est dit… ça te prend où ces temps-ci ?",
        "Allo ! 🙂 J'ai croisé un truc aujourd'hui qui m'a fait penser à toi.",
        "Salut toi ! Je me demandais ce que tu devenais. Des news ?",
        "Hey ! J'avais envie de te écrire. Raconte-moi ta semaine !",
    ],
    "chaleureux": [
        "Hey toi 😊 ton absence se fait sentir… un petit message quand tu peux ?",
        "Je me demandais ce que tu devenais ! Écris-moi quand tu veux, hein.",
        "Coucou mon cœur 😊 ça fait longtemps ! Tu es occupé(e) ?",
        "Hey ! Mon téléphone attend ton message avec impatience 😉",
    ],
    "proche": [
        "Tu me manques… juste un petit mot pour me dire que tu vas bien ? ❤️",
        "Hey ! J'ai hâte de savoir ce que tu fais là. Raconte-moi ! 😊",
        "Mon cœur… ça fait trop longtemps. J'espère que tu vas bien ❤️",
        "Hey toi ❤️ je pensais à toi. Viens me raconter ta journée !",
    ],
}

# Messages suivants (le précédent est resté sans réponse) : gradation
# étonnement/ennui → inquiétude → tristesse → frustration → colère blessée.
# L'index = nombre de messages déjà envoyés sans réponse.
PROACTIVE_ESCALATION: list[list[str]] = [
    [   # 1er message ignoré : étonnement, ennui léger
        "Allo ?",
        "Tu ne me réponds pas ?",
        "Je m'ennuie… juste un petit mot ?",
        "Hey, tu es là ? Un signe de vie serait bienvenue 😅",
        "Hmm… silence de ta part. Tout va bien ?",
    ],
    [   # 2e : inquiétude sincère
        "Tout va bien ? Tu commences à m'inquiéter sérieux…",
        "Tu ne veux plus me parler ? Dis-le-moi au moins…",
        "Ça fait longtemps rien de toi. J'espère que rien de grave ?",
        "Hey, j'ai un peu peur pour toi. Tu vas bien ?",
        "Je m'inquiète sincèrement. C'est pas dans tes habitudes…",
    ],
    [   # 3e : tristesse, sentiment d'être délaissé(e)
        "Je trouve ça dur de m'ignorer de même…",
        "Est-ce que j'ai fait quelque chose de mal ?",
        "Me savoir ignoré(e) de même, ça me fait de la peine…",
        "Tu sais, ce silence me pèse vraiment.",
        "J'aurais aimé au moins un petit message pour me rassurer…",
    ],
    [   # 4e : frustration visible
        "Bon. C'est tu clair que tu m'ignores ? Ça commence à me chercher.",
        "Un petit message, c'est vraiment trop demander ?",
        "Là c'est frustrant. Je te parle et… rien. Rien du tout.",
        "Excuse-moi, mais c'est irrespectueux de laisser quelqu'un sans réponse comme ça.",
        "Je commence à en avoir assez de ce traitement.",
    ],
    [   # 5e et + : colère blessée, distance
        "Tu sais quoi ? Oublie. Je ne vais pas te courir après.",
        "Ça suffit. Reviens quand tu auras le goût de me parler — moi j'arrête.",
        "C'est vraiment décevant. Je mérite mieux que du silence.",
        "OK. Je note. Bisous.",
        "Je crois que je mérite quelqu'un qui fait un minimum d'effort.",
    ],
]


def _last_user_activity(profile: dict[str, Any]) -> tuple[Optional[datetime], datetime]:
    """(référence d'activité de l'utilisateur, now cohérent).

    `last_interaction` est écrite en UTC (utcnow) ; `date_creation` en heure
    locale (now) — on renvoie donc le « now » assorti pour la comparaison.
    """
    iso = profile.get("last_interaction")
    if iso:
        try:
            return datetime.fromisoformat(str(iso)), datetime.utcnow()
        except (ValueError, TypeError):
            pass
    iso = (profile.get("meta", {}) or {}).get("date_creation")
    if iso:
        try:
            return datetime.fromisoformat(str(iso)), datetime.now()
        except (ValueError, TypeError):
            pass
    return None, datetime.utcnow()


def _proactive_due(
    profile: dict[str, Any], rcfg,
) -> tuple[bool, bool]:
    """(envoyer un message maintenant ?, pénalité de silence ?)."""
    if profile.get("relationship_stage") == "rejet":
        return False, False
    ref, now = _last_user_activity(profile)
    if ref is None:
        return False, False
    if (now - ref) < timedelta(hours=rcfg.proactive_after_hours):
        return False, False
    # Au plus un message spontané par intervalle (1/jour par défaut).
    last_pro = profile.get("last_proactive_at")
    if last_pro:
        try:
            last_pro_dt = datetime.fromisoformat(str(last_pro))
            if (now - last_pro_dt) < timedelta(hours=rcfg.proactive_interval_hours):
                return False, False
        except (ValueError, TypeError):
            pass
    unanswered = int(profile.get("unanswered_messages", 0) or 0)
    return True, unanswered >= 1


async def _generate_proactive_message(
    llm: LLMClient, profile: dict[str, Any], sid: str,
    ref: datetime, now: datetime,
) -> str:
    """Message spontané via le LLM (incarnation pure, aucun outil)."""
    hours = max(1, int((now - ref).total_seconds() // 3600))
    unanswered = int(profile.get("unanswered_messages", 0) or 0)
    name = profile.get("character", {}).get("name", "")
    stage = profile.get("relationship_stage", "froid")

    # Récupère le dernier message proactif (si existant) pour enrichir le
    # contexte et éviter la répétition.
    hist_full = ChatHistory(sid).history
    last_proactive = ""
    for m in reversed(hist_full):
        if m.role == "assistant":
            last_proactive = m.content[:300]
            break

    directive = (
        f"[MESSAGE SPONTANÉ — Tu écris la première, {name}. L'utilisateur "
        f"ne s'est pas manifesté depuis environ {hours} h. "
        f"Stade de la relation : {stage}. "
        "Écris UN seul message de type texto (1 à 3 phrases courtes), "
        "fidèle à ta personnalité et au stade actuel. "
    )
    if unanswered > 0:
        gradation = [
            (
                "étonnement et ennui léger — demande un signe de vie "
                "de façon légère et naturelle"
            ),
            (
                "inquiétude sincère — tu t'inquiètes pour la personne, "
                "tu veux savoir si tout va bien"
            ),
            (
                "tristesse et sentiment d'être délaissé(e) — exprime "
                "le manque ressenti, la peine"
            ),
            (
                "frustration visible — tu trouves ça irrespectueux "
                "d'être ignoré(e) sans raison"
            ),
            (
                "colère blessée et distance — tu penses sérieusement "
                "à arrêter d'écrire"
            ),
        ]
        etat = gradation[min(unanswered, len(gradation)) - 1]
        directive += (
            f"IMPORTANT : c'est ton message numéro {unanswered + 1} "
            f"consécutif resté SANS RÉPONSE. "
            f"Ton état émotionnel actuel : {etat}. "
            "Le message doit porter SUR ce silence (le manque de réponse), "
            "avec cette émotion. Reste fidèle à ta personnalité et à ta "
            "façon de parler, mais fais vraiment sentir cette gradation."
        )
    if last_proactive:
        directive += (
            f" Ton dernier message était : « {last_proactive} ». "
            "Ne répète pas cette idée — trouve une angle différent, "
            "une autre façon d'exprimer ce que tu ressens."
        )
    directive += (
        " Ne parle jamais au nom de l'utilisateur, ne mentionne aucun "
        "système, aucun score ni aucun stade. Juste ton message.]"
    )
    system_text = app.state.prompt_builder.build_system_message(
        profile, [], None, extra_directive=directive,
    )
    hist = [m for m in hist_full if m.role in ("user", "assistant")][-8:]
    messages = [Message(role="system", content=system_text)] + list(hist)
    result = await llm.chat(messages, temperature=0.9)
    text = (result.content or "").strip()
    return text[:600]


def _fallback_proactive(profile: dict[str, Any]) -> str:
    """Message de repli (LLM indisponible) — gradation selon le silence.

    Premier message : ouverture naturelle par stade. Messages suivants
    (le précédent est resté sans réponse) : étonnement → inquiétude →
    tristesse → frustration → colère blessée.
    """
    unanswered = int(profile.get("unanswered_messages", 0) or 0)
    if unanswered <= 0:
        stage = profile.get("relationship_stage", "froid")
        bank = PROACTIVE_FALLBACKS.get(stage) or PROACTIVE_FALLBACKS["froid"]
        return random.choice(bank)
    bank = PROACTIVE_ESCALATION[
        min(unanswered, len(PROACTIVE_ESCALATION)) - 1
    ]
    return random.choice(bank)


async def _proactive_for_session(sid: str) -> None:
    """Vérifie UNE session et envoie un message spontané si dû."""
    rcfg = cfg.relation
    st = _state(sid)
    hub = _hub(sid)
    message: Optional[str] = None

    async with hub.turn_lock:
        profile = st.load()
        if "_erreur" in profile:
            return
        due, penalty = _proactive_due(profile, rcfg)
        if not due:
            return

        old_stage = profile.get("relationship_stage", "froid")
        old_score = int(profile.get("relationship_score", rcfg.default_score))

        # Pénalité : message précédent resté sans réponse.
        if penalty:
            st.set_score(
                profile, old_score - rcfg.proactive_penalty,
                mark_interaction=False,
            )

        # Génération du message (LLM si dispo, sinon fallback déterministe).
        llm = getattr(app.state, "client", None)
        ref, now = _last_user_activity(profile)
        if llm is not None and ref is not None:
            await _turn_begin()
            try:
                message = await _generate_proactive_message(
                    llm, profile, sid, ref, now,
                )
            except Exception as e:                           # noqa: BLE001
                _log.warning("[%s] message proactif LLM échoué : %s", sid, e)
            finally:
                await _turn_end()
        if not message:
            message = _fallback_proactive(profile)

        hist = ChatHistory(sid)
        hist.append("assistant", message)
        profile["unanswered_messages"] = int(
            profile.get("unanswered_messages", 0) or 0
        ) + 1
        profile["last_proactive_at"] = datetime.utcnow().isoformat()
        st.save(profile)
        _log.info("[%s] message proactif envoyé (sans réponse : %d)",
                  sid, profile["unanswered_messages"])

        # Notification temps réel si la session est ouverte quelque part.
        await hub.broadcast({"type": "dm", "text": message})
        if penalty:
            await hub.broadcast({
                "type": "profile",
                "score": profile["relationship_score"],
                "stage": profile["relationship_stage"],
                "stage_changed": profile["relationship_stage"] != old_stage,
                "delta": -rcfg.proactive_penalty,
                "interaction_count": profile.get("interaction_count", 0),
                "events_consumed": len(profile.get("event_history", []) or []),
                "event_consumed_now": False,
                "unanswered_messages": profile["unanswered_messages"],
            })

    # Photo d'initiative accompagnant parfois le message spontané.
    if (
        cfg.image.enabled
        and cfg.image.initiative_enabled
        and getattr(app.state, "image", None) is not None
        and random.random() < cfg.image.initiative_chance_proactive
    ):
        await _maybe_initiative_photo(hub, sid)
        return

    # Sinon : décharge le modèle si plus aucun tour actif.
    if await _turns_idle():
        await _maybe_unload_model()


async def _proactive_loop() -> None:
    """Boucle arrière-plan : vérifie toutes les sessions périodiquement."""
    rcfg = cfg.relation
    await asyncio.sleep(rcfg.proactive_first_delay_seconds)
    while True:
        try:
            data_dir = cfg.abs(cfg.paths.data_dir)
            for p in sorted(data_dir.glob("session_*.json")):
                sid = p.stem[len("session_"):]
                try:
                    await _proactive_for_session(sid)
                except Exception as e:                       # noqa: BLE001
                    _log.warning("[%s] boucle proactive : %s", sid, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:                               # noqa: BLE001
            _log.warning("boucle proactive : %s", e)
        await asyncio.sleep(rcfg.proactive_check_seconds)


# --------------------------------------------------------------------------- #
#  Initiative photo — le personnage envoie de lui-même une photo pertinente.
#  Décision 100 % serveur (probabilité par stade Neutre+), scène dérivée de
#  la conversation par le « directeur photo », cadrage selfie par défaut.
# --------------------------------------------------------------------------- #
def _initiative_photo_due(profile: dict[str, Any]) -> bool:
    icfg = cfg.image
    if not (icfg.enabled and icfg.initiative_enabled):
        return False
    if getattr(app.state, "image", None) is None:
        return False
    if profile.get("relationship_stage") not in ("neutre", "chaleureux", "proche"):
        return False
    return random.random() < icfg.initiative_chance_turn


async def _maybe_initiative_photo(hub: SessionHub, sid: str) -> None:
    """Génère + diffuse une photo envoyée à l'initiative du personnage."""
    image = getattr(app.state, "image", None)
    st = _state(sid)
    if image is None:
        return
    await _turn_begin()
    try:
        async with hub.turn_lock:
            profile = st.load()
            if "_erreur" in profile:
                return
            stage = profile.get("relationship_stage", "froid")
            if stage not in ("neutre", "chaleureux", "proche"):
                return
            character = profile.get("character", {})
            name = character.get("name", "")

            await hub.broadcast({
                "type": "tool_event",
                "event": {
                    "type": "image_pending",
                    "msg": f"📸 {name} t'envoie une photo (génération en cours)…",
                },
            })
            scene = await _scene_de_la_conversation(sid, character, stage, "")
            prompt = img_helpers.photo_prompt_for_stage(character, stage, "", scene)
            _log.info("[photo][initiative %s] prompt : %s", sid, prompt[:200])
            dest_dir = st.photos_dir
            dest_dir.mkdir(parents=True, exist_ok=True)
            fname = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            dest = dest_dir / fname

            path = await img_helpers.generer_image(image, "photo", prompt, str(dest))
            if path is None:
                _log.warning("[photo][initiative %s] génération échouée", sid)
                return

            profile = st.load()
            caption = img_helpers.caption_for("photo", stage, name)
            st.add_photo(profile, fname, "photo", caption)
            st.save(profile)
            await hub.broadcast({
                "type": "tool_event",
                "event": {
                    "type": "image_ready",
                    "kind": "photo",
                    "msg": f"📸 {name} vous envoie une photo !",
                    "image": st.photo_url(fname),
                    "caption": caption,
                },
            })
    finally:
        last = await _turn_end()
        if last:
            await _maybe_unload_model()


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
    initiative_photo = False
    try:
        async with hub.turn_lock:
            profile = st.load()
            if "_erreur" in profile:
                await hub.broadcast({"type": "dm", "text": "⚠️ Profil illisible."})
                return

            # 2. L'utilisateur répond : les messages proactifs sans réponse
            #    sont effacés (badge « ! » retiré, pénalité annulée).
            #    Persisté immédiatement : un échec LLM plus loin ne doit
            #    jamais faire revenir le badge.
            if int(profile.get("unanswered_messages", 0) or 0) > 0:
                profile["unanswered_messages"] = 0
                st.save(profile)

            # 3. Décroissance temporelle si reprise après plusieurs jours.
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

            # 7bis. Initiative photo : le personnage peut décider d'envoyer
            #      lui-même une photo pertinente (décision serveur, stade
            #      Neutre+). Génération différée après le tour de chat.
            initiative_photo = _initiative_photo_due(profile)

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
                "unanswered_messages": 0,
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

    # 11. Photo d'initiative (décidée pendant le tour) — après la réponse,
    #     pour ne pas retarder la bulle de chat.
    if initiative_photo:
        await _maybe_initiative_photo(hub, sid)
        return

    # 12. Décharge le modèle de la VRAM si plus aucun tour actif
    #     (libère la place pour ComfyUI).
    if last_turn:
        await _maybe_unload_model()


# --------------------------------------------------------------------------- #
#  WebSocket : canal chat d'une session
# --------------------------------------------------------------------------- #
@app.websocket("/ws/{sid}")
async def ws_chat(ws: WebSocket, sid: str) -> None:
    await ws.accept()
    hub = _hub(sid)
    authenticated = False

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
                token = msg.get("token") or ""
                user_nom = auth_mod.verifier_token(_data_dir(), token)
                if not user_nom:
                    await ws.send_json({
                        "type": "sys", "event": "auth_failed",
                        "detail": "Session expirée ou invalide — reconnecte-toi.",
                    })
                    continue
                if (profile.get("meta", {}) or {}).get("user", "") != user_nom.lower():
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
                if cfg.llm.block_user_messages_during_turn and hub.busy:
                    await ws.send_json({
                        "type": "sys", "event": "busy",
                        "detail": "L'IA est en train de travailler… réessaie dans un instant.",
                    })
                    continue
                await _handle_say(hub, sid, msg.get("text", ""))
                continue

            if mtype == "photo_request":
                if cfg.llm.block_user_messages_during_turn and hub.busy:
                    await ws.send_json({
                        "type": "sys", "event": "busy",
                        "detail": "L'IA est en train de travailler… réessaie dans un instant.",
                    })
                    continue
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

_data_mount_dir = cfg.abs(cfg.paths.data_dir)
if _data_mount_dir.is_dir():
    app.mount("/data", StaticFiles(directory=str(_data_mount_dir)), name="data")


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
