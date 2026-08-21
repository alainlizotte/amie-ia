"""Personnages prédéfinis et scénarios d'événements.

Portage de la logique presets du projet OpenWebUI d'origine :
- chargement (cache) de `characters.json` / `events.json` ;
- sélection du prochain événement avec gates par stade
  (floor global `neutre`, gate I/J `chaleureux`, gate duale stricte pour K) ;
- marquage de consommation.

La sélection d'un personnage se fait désormais via le GUI (formulaire de
création de session) — plus besoin de détection par regex dans le message.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .stages import STAGE_ORDER, can_play_stage

# Dossier des presets : variable d'env PRESETS_DIR, sinon ./data/character_presets
# à la racine du projet, sinon chemin monté en Docker.
_PROJECT_ROOT_GUESS = Path(__file__).resolve().parent.parent.parent
_LOCAL_PRESETS = _PROJECT_ROOT_GUESS / "data" / "character_presets"
_CONTAINER_PRESETS = Path("/app/data/character_presets")
if os.environ.get("PRESETS_DIR"):
    PRESETS_DIR = Path(os.environ["PRESETS_DIR"])
elif _LOCAL_PRESETS.is_dir():
    PRESETS_DIR = _LOCAL_PRESETS
else:
    PRESETS_DIR = _CONTAINER_PRESETS

_PRESETS_CHARACTERS_CACHE: Optional[list[dict]] = None
_EVENTS_BY_CHARACTER_CACHE: Optional[dict[str, list[dict]]] = None


def _load_json_file(path: Path):
    """Charge un JSON depuis le disque ou renvoie None si absent/illisible."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def load_preset_characters() -> list[dict]:
    """Charge et met en cache les personnages prédéfinis."""
    global _PRESETS_CHARACTERS_CACHE
    if _PRESETS_CHARACTERS_CACHE is not None:
        return _PRESETS_CHARACTERS_CACHE
    data = _load_json_file(PRESETS_DIR / "characters.json")
    _PRESETS_CHARACTERS_CACHE = data if isinstance(data, list) else []
    return _PRESETS_CHARACTERS_CACHE


def load_preset_events() -> dict[str, list[dict]]:
    """Charge et indexe les scénarios par character_id."""
    global _EVENTS_BY_CHARACTER_CACHE
    if _EVENTS_BY_CHARACTER_CACHE is not None:
        return _EVENTS_BY_CHARACTER_CACHE
    path = PRESETS_DIR / "events.json"
    data = _load_json_file(path)
    blocks = data if isinstance(data, list) else []
    _EVENTS_BY_CHARACTER_CACHE = {
        b.get("character_id"): b.get("events", [])
        for b in blocks
        if isinstance(b, dict)
    }
    return _EVENTS_BY_CHARACTER_CACHE


def get_preset_character(character_id: str) -> Optional[dict]:
    """Retourne le dict du personnage prédéfini correspondant, ou None."""
    for c in load_preset_characters():
        if c.get("id") == character_id:
            return c
    return None


def get_events_for_character(character_id: str) -> list[dict]:
    return load_preset_events().get(character_id, [])


# --------------------------------------------------------------------------- #
#  Sélection du prochain scénario (gates par stade — voir README d'origine)
# --------------------------------------------------------------------------- #
def get_pending_event(
    profile: dict[str, Any],
    current_stage: str,
    cooldown_hours: float = 24.0,
) -> Optional[dict]:
    """Renvoie le prochain événement disponible pour une session, ou None.

    Logique (identique au projet d'origine) :
      1. Un preset doit être attaché au personnage de la session.
      2. GATE GLOBALE : aucun event avant le stade « neutre » (score >= 400).
      3. Cooldown respecté depuis last_event_at.
      4. Candidats : non consommés + can_play_stage(min_stage, stade).
      5. K (final) : gate DUALE STRICTE — stade « proche » ET tous les A-J
         consommés. Priorité maximale s'il est débloqué.
      6. Sinon priorité aux intimes (I/J), puis A-H dans l'ordre.
    """
    character = profile.get("character") or {}
    preset_id = character.get("preset_id")
    if not preset_id:
        return None

    # Gate globale : rien avant « neutre ».
    if (
        current_stage not in STAGE_ORDER
        or STAGE_ORDER.index(current_stage) < STAGE_ORDER.index("neutre")
    ):
        return None

    history = profile.get("event_history", []) or []
    last_event_at = profile.get("last_event_at")

    if last_event_at and cooldown_hours and cooldown_hours > 0:
        try:
            last_dt = datetime.fromisoformat(last_event_at)
            elapsed = datetime.utcnow() - last_dt
            if elapsed < timedelta(hours=cooldown_hours):
                return None
        except (ValueError, TypeError):
            pass  # timestamp illisible → on ignore le cooldown

    events = get_events_for_character(preset_id)
    if not events:
        return None

    candidates = [
        e for e in events
        if e.get("event_id") not in history
        and can_play_stage(e.get("min_stage"), current_stage)
    ]
    if not candidates:
        return None

    candidates_without_k = [e for e in candidates if e.get("letter") != "K"]
    k_candidates = [e for e in candidates if e.get("letter") == "K"]

    if k_candidates:
        k_event = k_candidates[0]
        stage_proche_ok = current_stage == "proche"
        aj_event_ids = {
            e["event_id"] for e in events if e.get("letter") in "ABCDEFGHIJ"
        }
        aj_consumed = aj_event_ids & set(history)
        aj_all_consumed = bool(aj_event_ids) and aj_consumed == aj_event_ids
        if stage_proche_ok and aj_all_consumed:
            return k_event
        # K reste invisible tant que sa gate duale n'est pas satisfaite.

    intimate = [
        e for e in candidates_without_k
        if e.get("tone") in ("intimate_slow_build", "intimate_consummation")
    ]
    if intimate:
        return intimate[0]
    return candidates_without_k[0] if candidates_without_k else None


def mark_event_consumed(profile: dict[str, Any], event_id: str) -> None:
    """Marque un événement comme consommé dans le profil (en mémoire ;
    l'appelant persiste via RelationState.save)."""
    history = profile.setdefault("event_history", [])
    if event_id not in history:
        history.append(event_id)
    profile["last_event_at"] = datetime.utcnow().isoformat()
    profile["last_injected_event_id"] = None
    attempts = profile.setdefault("event_attempts", {})
    attempts.pop(event_id, None)


def build_character_from_preset(preset: dict) -> dict:
    """Construit le bloc `character` du profil à partir d'un preset."""
    parcours = preset.get("parcours", {}) or {}
    return {
        "preset_id": preset.get("id"),
        "name": preset.get("name", ""),
        "age": preset.get("age", ""),
        "title": preset.get("title", ""),
        "gender": preset.get("gender", ""),
        "occupation": parcours.get("professionnel", "") or preset.get("title", ""),
        "interests": preset.get("centres_interet", ""),
        "appearance": preset.get("appearance", ""),
        "personality": preset.get("personality", ""),
        "parcours": parcours,
        "histoire_personnelle": preset.get("histoire_personnelle", ""),
        "parcours_amoureux": preset.get("parcours_amoureux", ""),
    }
