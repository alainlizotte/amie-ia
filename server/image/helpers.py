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


def photo_prompt_for_stage(
    character: dict[str, Any],
    stage: str,
    user_hint: str = "",
) -> str:
    """Prompt d'une photo demandée en cours de session — contraint par stade.

    `user_hint` : contexte optionnel saisi dans le GUI (lieu, ambiance…).
    """
    desc = _base_description(character)
    hint = f", {user_hint.strip()}" if user_hint and user_hint.strip() else ""

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
        f"photograph of {desc}{hint}, {outfit}, "
        "photorealistic, natural lighting, warm colors, "
        "romantic dating profile photo style, high resolution, no text"
    )


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
