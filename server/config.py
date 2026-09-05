"""Charge et valide la configuration YAML de l'application Ami(e) IA.

Dataclasses hydratées depuis
`config/config.yaml`, valeurs par défaut sûres, clés inconnues ignorées.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class LLMConfig:
    backend: str = "llamacpp"        # "ollama" | "llamacpp"
    base_url: str = "http://llamacpp:8080/v1"
    api_key: str = "none"
    model: str = "gemma-4-E4B-it-Q4_0"
    temperature: float = 1.0
    top_p: float = 0.95
    max_context_tokens: int = 16384
    max_tokens: int = 8192           # plafond de génération par réponse (llama.cpp -n)
    think: bool = False              # désactive le thinking (Gemma 4, Qwen3…)
    # Déchargement du modèle après le tour :
    # - True  : comportement historique — la VRAM est libérée dès la fin du
    #           dernier tour actif (partage du GPU avec ComfyUI).
    # - False : le modèle reste chargé et n'est déchargé qu'après
    #           `unload_delay_minutes` minutes d'inactivité — utile avec plus
    #           de RAM/VRAM : les tours consécutifs évitent de recharger le
    #           modèle (gain de plusieurs secondes par tour).
    unload_after_turn: bool = True
    unload_delay_minutes: float = 5.0
    # Bloque les messages des utilisateurs pendant que l'IA travaille
    # (réfléchit, écrit ou génère une image) — évite les tours concurrents.
    block_user_messages_during_turn: bool = True
    # Streaming de la réponse vers le(s) client(s) :
    # - True  : les tokens sont diffusés au fil de l'eau (défaut).
    # - False : la réponse complète est diffusée en un seul bloc à la fin
    #           du tour (le client ne voit rien pendant la génération).
    stream_to_clients: bool = True
    # Options natives transmises au backend (ex: num_ctx, top_k, …).
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5174", "http://127.0.0.1:8000"]
    )


@dataclass
class PathsConfig:
    data_dir: str = "./server/data"
    prompts_dir: str = "./server/prompts"


@dataclass
class RelationConfig:
    """Paramètres de la mécanique relationnelle — 100 % côté serveur,
    indépendants du LLM (le modèle ne peut ni les contourner ni les calculer)."""
    default_score: int = 100          # deux inconnus qui se rencontrent
    delta_max: int = 16               # plafond de progression par message
    delta_min: int = -20              # plancher de régression par message
    cooldown_hours: float = 24.0      # délai min entre deux scénarios injectés
    event_max_attempts: int = 3       # tours max avant consommation forcée d'un event
    event_consume_similarity: float = 0.55   # similarité cosinus event ↔ réponse
    decay_days_grace: int = 3         # jours d'absence avant décroissance
    decay_points_per_day: int = 10    # points perdus par jour d'absence
    decay_max_loss: int = 150         # perte maximale cumulée par décroissance
    summarize_every_turns: int = 10   # fréquence d'extraction de souvenirs
    max_memories: int = 40            # nombre max de souvenirs stockés (FIFO)
    # Messages proactifs du personnage (il écrit le premier après un silence)
    proactive_enabled: bool = True
    proactive_after_hours: float = 24.0   # silence requis avant initiative
    proactive_interval_hours: float = 24.0  # délai min entre deux initiatives (1/jour)
    proactive_penalty: int = 50         # pénalité si nouveau message sans réponse au précédent
    proactive_check_seconds: int = 300  # période de la boucle de vérification
    proactive_first_delay_seconds: int = 30  # délai avant la première vérification


@dataclass
class MemoryConfig:
    """Souvenirs sémantiques — embeddings via le serveur llamaembed dédié."""
    enabled: bool = True
    embedding_base_url: str = "http://llamaembed:8080/v1"
    embedding_model: str = "embeddinggemma"
    top_k: int = 6                    # souvenirs rappelés par tour
    min_similarity: float = 0.30      # seuil de rappel (cosinus)


@dataclass
class ImageConfig:
    enabled: bool = True
    base_url: str = ""                # vide → env COMFYUI_BASE_URL → défaut local
    timeout_total: int = 300
    # Initiative du personnage : il envoie de lui-même des photos pertinentes
    initiative_enabled: bool = True
    initiative_chance_turn: float = 0.10       # proba par tour de conversation
    initiative_chance_proactive: float = 0.30  # proba avec un message spontané


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    relation: RelationConfig = field(default_factory=RelationConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    image: ImageConfig = field(default_factory=ImageConfig)
    raw: dict[str, Any] = field(default_factory=dict)
    project_root: Path = Path(__file__).resolve().parent.parent

    def abs(self, path: str) -> Path:
        """Résout `path` (relatif ou absolu) depuis la racine projet."""
        p = Path(path)
        return p if p.is_absolute() else (self.project_root / p).resolve()


def _coerce(dataclass_cls, data: dict[str, Any]):
    """N'hydrate que les champs connus du dataclass pour éviter les crashes."""
    if not isinstance(data, dict):
        return dataclass_cls()
    fields = {f for f in dataclass_cls.__dataclass_fields__}
    return dataclass_cls(**{k: v for k, v in data.items() if k in fields})


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    """Charge config.yaml (et retombe sur les défauts si absent).

    Le chemin peut être imposé par la variable d'env AMIE_CONFIG
    (utilisé par docker-compose : /app/config/config.yaml).
    """
    project_root = Path(__file__).resolve().parent.parent
    if path is None:
        path = os.environ.get("AMIE_CONFIG") or (project_root / "config" / "config.yaml")
    path = Path(path)

    raw: dict[str, Any] = {}
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    cfg = AppConfig(
        llm=_coerce(LLMConfig, raw.get("llm", {})),
        server=_coerce(ServerConfig, raw.get("server", {})),
        paths=_coerce(PathsConfig, raw.get("paths", {})),
        relation=_coerce(RelationConfig, raw.get("relation", {})),
        memory=_coerce(MemoryConfig, raw.get("memory", {})),
        image=_coerce(ImageConfig, raw.get("image", {})),
        raw=raw,
        project_root=project_root,
    )

    # Overrides d'environnement (pratique en dev local hors Docker :
    # AMIE_LLM_BASE_URL=http://127.0.0.1:8080/v1 etc.)
    if os.environ.get("AMIE_LLM_BASE_URL"):
        cfg.llm.base_url = os.environ["AMIE_LLM_BASE_URL"]
    if os.environ.get("AMIE_MEMORY_EMBEDDING_BASE_URL"):
        cfg.memory.embedding_base_url = os.environ["AMIE_MEMORY_EMBEDDING_BASE_URL"]

    # S'assure que les dossiers critiques existent
    for p in (cfg.paths.data_dir, cfg.paths.prompts_dir):
        d = cfg.abs(p)
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return cfg


# Singleton chargé paresseusement
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(cfg: AppConfig) -> None:
    global _config
    _config = cfg
