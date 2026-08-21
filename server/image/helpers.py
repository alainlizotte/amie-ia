"""Helpers de génération d'images — prompts construits SANS le LLM.

Contrairement au projet d'origine (où le LLM devait penser à appeler
generate_image et construire lui-même le prompt visuel), ici :
- le portrait de référence est généré automatiquement à la création de la
  session, à partir des champs `appearance` / `age` / `interests` du profil ;
- les photos demandées pendant la session sont construites par le serveur,
  avec des contraintes de tenue déterminées par le STADE relationnel
  (garde-fou technique que le LLM ne peut pas contourner).

Échelle de tenue par stade :
- rejet / froid : aucune photo refusée côté GUI ;
- reserve / neutre : sobre, complètement habillée ;
- chaleureux : petite tenue / lingerie acceptée, jamais nue ;
- proche : sans restriction.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from .comfyui import ComfyUIError, ComfyUIBackend

_log = logging.getLogger("amie.image.helpers")

# Messages affichés aux utilisateurs (transmis via WS tool_event).
MSG_PENDING_PORTRAIT = (
    "📸 Photo de profil en cours de génération — cela peut prendre 30 à 60 secondes."
)
MSG_PENDING_PHOTO = "📸 Photo en cours de génération (jusqu'à 60 s)..."

# Refus déterministes par stade (aucun appel LLM nécessaire).
REFUSALS_BY_STAGE = {
    "rejet": "🚫 Impossible : le personnage ne souhaite même plus vous parler.",
    "froid": "🚫 Trop tôt : vous êtes encore des inconnus. Continuez la conversation.",
    "reserve": "🚫 Le personnage n'est pas encore à l'aise pour partager des photos.",
}


def get_backend(base_url: str = "", timeout_total: int = 300) -> Optional[ComfyUIBackend]:
    """Renvoie un backend ComfyUI prêt à l'emploi, ou None si désactivé."""
    try:
        return ComfyUIBackend(base_url=base_url, timeout_total=timeout_total)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Construction des prompts visuels (déterministe)
# --------------------------------------------------------------------------- #
def _pronoun(character: dict[str, Any]) -> str:
    g = (character.get("gender") or "F").upper()[:1]
    return "she" if g == "F" else "he" if g == "M" else "they"


def _possessive(character: dict[str, Any]) -> str:
    g = (character.get("gender") or "F").upper()[:1]
    return "her" if g == "F" else "his" if g == "M" else "their"


def _base_description(character: dict[str, Any]) -> str:
    parts: list[str] = []
    name = character.get("name", "")
    age = character.get("age", "")
    gender = character.get("gender", "")
    subject = "woman" if gender == "F" else "man" if gender == "M" else "person"
    if age:
        parts.append(f"{age} year old {subject}")
    elif subject != "person":
        parts.append(subject)
    if character.get("appearance"):
        parts.append(str(character["appearance"]))
    if character.get("interests"):
        parts.append(f"style reflecting interests in {character['interests']}")
    return ", ".join(parts)


def portrait_prompt(character: dict[str, Any]) -> str:
    """Photo de référence — vue intégrale, sobre (stade de départ « froid »)."""
    desc = _base_description(character)
    return (
        f"full body photograph of {desc}, standing pose from head to toe, "
        "casual stylish outfit, natural soft lighting, photorealistic, "
        "shallow depth of field, warm romantic atmosphere, high resolution, "
        "no text"
    )


def pov_clause(character: dict[str, Any]) -> str:
    """Point de vue constant : la photo est vue des YEUX de l'utilisateur."""
    p = _pronoun(character)
    verb = "look" if p == "they" else "looks"
    return (
        f"point of view photograph taken from the eyes of the person "
        f"{p} is talking to, {p} {verb} directly at you"
    )


def photo_prompt_for_stage(
    character: dict[str, Any],
    stage: str,
    user_hint: str = "",
    scene: str = "",
) -> str:
    """Prompt d'une photo demandée en cours de session — contraint par stade.

    `user_hint` : contexte optionnel saisi dans le GUI (lieu, ambiance…).
    `scene`     : fragments visuels dérivés de la conversation par le
                  « directeur photo » LLM (déjà sanitisés via sanitize_scene).
    Le point de vue est TOUJOURS celui de l'utilisateur (pov_clause).
    """
    desc = _base_description(character)
    hint = f", {user_hint.strip()}" if user_hint and user_hint.strip() else ""
    scene_part = f", {scene.strip(' ,.')}" if scene and scene.strip(" ,.") else ""

    if stage == "proche":
        outfit = "outfit unrestricted, intimate tasteful composition"
    elif stage == "chaleureux":
        outfit = (
            "wearing revealing casual outfit or elegant lingerie, "
            "sensual but never nude, tasteful pose"
        )
    else:  # neutre / reserve
        outfit = (
            "fully dressed in a sober stylish outfit, modest pose, "
            "nothing suggestive"
        )

    return (
        f"photograph of {desc}{hint}{scene_part}, {outfit}, "
        f"{pov_clause(character)}, "
        "photorealistic, natural lighting, warm colors, "
        "romantic dating profile photo style, high resolution, no text"
    )


# --------------------------------------------------------------------------- #
#  Directeur photo : scène dérivée de la conversation (appel LLM côté serveur)
# --------------------------------------------------------------------------- #
_CLOTHING_RULES = {
    "proche": "no clothing restriction",
    "chaleureux": (
        "revealing outfit or elegant lingerie allowed, but never nude"
    ),
}
_CLOTHING_RULE_DEFAULT = "fully dressed, sober outfit, nothing suggestive"

_MOTS_NUDITE = re.compile(
    r"\b(nude|naked|nudity|topless|undressed|unclothed|no clothes|"
    r"without clothes|nsfw|nue|dénudée?|sans v[êe]tements)\b",
    re.IGNORECASE,
)


def sanitize_scene(scene: str, stage: str) -> str:
    """Nettoie les fragments de scène produits par le LLM.

    - supprime toute mention de nudité tant que le stade n'est pas « proche »
      (garde-fou dur : le LLM ne peut pas contourner les règles de tenue) ;
    - retire guillemets et retours à la ligne, borne la longueur.
    """
    s = str(scene or "").replace('"', " ")
    if stage != "proche":
        s = _MOTS_NUDITE.sub("", s)
    s = " ".join(s.split())
    if stage != "proche":
        s = ", ".join(p.strip(" ,") for p in s.split(",") if p.strip(" ,"))
    return s[:300].strip(" ,.")


def director_system(character: dict[str, Any], stage: str,
                    user_request: str = "") -> str:
    """Consigne système du « directeur photo » (appel chat non-streaming).

    `user_request` : demande explicite de l'utilisateur (champ au moment du
    📷). Elle a priorité sur la scène générique si le personnage l'a
    acceptée dans la conversation.
    """
    p = _pronoun(character)
    poss = _possessive(character)
    name = character.get("name") or "the character"
    rule = _CLOTHING_RULES.get(stage, _CLOTHING_RULE_DEFAULT)
    lines = [
        "You are the art director of a photorealistic photo generator.",
        f"Based on the END of this conversation with {name}, describe ONLY "
        f"the current visual scene: place/location, where {p} is, "
        f"{poss} pose, {poss} action, {poss} gaze toward the viewer.",
        "If the user made a specific request in the conversation and "
        f"{name} accepted it, agreed to it or is doing it, that request "
        "has TOP PRIORITY — describe exactly what was asked.",
        "Output short comma-separated English fragments, maximum 30 words, "
        "no full sentences. Strictly consistent with what was said or done.",
        f"Clothing level allowed: {rule}.",
        "No camera jargon, no quality adjectives, no text or watermarks.",
    ]
    if user_request and user_request.strip():
        lines.insert(
            3,
            f"The user explicitly asks for THIS photo: "
            f"{user_request.strip()[:200]}",
        )
    return " ".join(lines)


# --------------------------------------------------------------------------- #
#  Génération avec cache + fallback silencieux
# --------------------------------------------------------------------------- #
async def generer_image(
    backend: ComfyUIBackend,
    usage: str,
    prompt: str,
    dest_path: str,
) -> Optional[str]:
    """Génère une image ; renvoie le chemin ou None (fallback silencieux)."""
    try:
        path, _seed = await backend.generer(usage, prompt, dest_path)
        if os.path.isfile(path):
            return path
    except ComfyUIError as e:
        _log.warning("[image] échec génération %s : %s", usage, e)
    except Exception as e:  # inattendue — tracée pour diagnostic
        _log.warning("[image] erreur inattendue %s : %r", usage, e)
    return None


def caption_for(kind: str, stage: str, character_name: str) -> str:
    """Légende FR affichée sous la photo dans l'album."""
    labels = {
        "portrait": f"Photo de profil de {character_name}",
        "photo": f"Photo partagée ({stage})",
    }
    return labels.get(kind, "Photo")
