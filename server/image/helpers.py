"""Helpers de génération d'images — prompts construits SANS le LLM.

Contrairement au projet d'origine (où le LLM devait penser à appeler
generate_image et construire lui-même le prompt visuel), ici :
- le portrait de référence est généré automatiquement à la création de la
  session, à partir des champs `appearance` / `age` / `interests` du profil ;
- les photos demandées pendant la session sont construites par le serveur,
  avec des contraintes de tenue déterminées par le STADE relationnel
  (garde-fou technique que le LLM ne peut pas contourner).

Échelle de tenue par stade :
- rejet / froid / reserve : photo refusée (message déterministe côté serveur) ;
- neutre : sobre, complètement habillée ;
- chaleureux : petite tenue / lingerie acceptée, jamais nue ;
- proche : sans restriction — nudité explicite autorisée (désactivable via
  `image.allow_explicit_from_proche: false`).
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

# Stade à partir duquel la nudité explicite est autorisée (garde-fou dur :
# le LLM ne peut RIEN générer d'explicite avant, même s'il le demandait).
# Désactivable globalement via `image.allow_explicit_from_proche: false`.
STAGE_EXPLICITE = "proche"


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


def _reflexive(character: dict[str, Any]) -> str:
    g = (character.get("gender") or "F").upper()[:1]
    return "herself" if g == "F" else "himself" if g == "M" else "themself"


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


def selfie_clause(character: dict[str, Any]) -> str:
    """Cadrage par défaut : la photo est un SELFIE pris par le personnage
    lui-même — appareil photo (téléphone) tenu dans sa main, bras tendu.
    Remplace l'ancien cadrage « vue des yeux de l'utilisateur »."""
    p = _pronoun(character)
    poss = _possessive(character)
    refl = _reflexive(character)
    return (
        f"casual selfie taken by {refl}, phone held in {poss} own hand "
        f"at arm's length, slightly high angle, {poss} extended arm "
        "visible at the edge of the frame, natural amateur selfie "
        "composition, mild lens distortion"
    )


# Mots-clés signalant qu'un cadrage alternatif est explicitement demandé
# (dans la scène du directeur photo ou le hint utilisateur) — dans ce cas,
# le selfie par défaut n'est PAS imposé (« sauf avis contraire »).
_FRAMING_HINT_RE = re.compile(
    r"\b(selfie|mirror|miroir|point of view|pov|taken by|held by|"
    r"photographer|someone else|stranger|passer-?by|tripod|"
    r"holding the camera|photobooth|prise par|prise de vue|"
    r"photographe|quelqu.un d.autre|appareil sur pied)\b",
    re.IGNORECASE,
)


def _wants_alt_framing(*fragments: str) -> bool:
    """True si un fragment (scène, hint) réclame explicitement un autre cadrage."""
    return any(_FRAMING_HINT_RE.search(f or "") for f in fragments)


def outfit_clause(stage: str, explicit: bool = True) -> str:
    """Contrainte de tenue par stade — toujours présente (garde-fou dur).

    `explicit` : au stade « proche » uniquement, autorise la nudité explicite
    (désactivable via `image.allow_explicit_from_proche`). Sans effet aux
    autres stades, où la pudeur reste imposée.
    """
    if stage == STAGE_EXPLICITE:
        if explicit:
            return (
                "outfit unrestricted — the state of dress described above is "
                "fully allowed, including complete nudity, topless or "
                "partially undressed, explicit nudity permitted, no censorship"
            )
        return (
            "outfit unrestricted but never nude, intimate tasteful composition"
        )
    if stage == "chaleureux":
        return (
            "wearing revealing casual outfit or elegant lingerie, "
            "sensual but never nude, tasteful pose"
        )
    # neutre / reserve
    return (
        "fully dressed in a sober stylish outfit, modest pose, "
        "nothing suggestive"
    )


def photo_prompt_for_stage(
    character: dict[str, Any],
    stage: str,
    user_hint: str = "",
    scene: str = "",
    explicit: bool = True,
) -> str:
    """Prompt d'une photo demandée en cours de session — contraint par stade.

    `user_hint` : contexte optionnel saisi dans le GUI (lieu, ambiance…).
    `scene`     : description complète produite par le « directeur photo »
                  (apparence actuelle, tenue RÉELLE portée, lieu, pose,
                  regard — déjà sanitizée via sanitize_scene).
    `explicit`  : au stade « proche », autorise la nudité explicite
                  (voir `image.allow_explicit_from_proche`).

    Quand la scène existe, elle fait foi SEULE pour l'apparence/la tenue :
    la fiche du personnage n'est PAS réinjectée (son style quotidien —
    « elle porte des robes fluides » — contredirait une scène où elle est
    nue ou autrement habillée, et noierait le modèle d'image sous des
    directives contradictoires). La clause de tenue du stade reste
    systématiquement ajoutée en garde-fou.

    Cadrage par défaut : SELFIE (téléphone tenu dans sa main, bras tendu)
    — imposé sauf si la scène ou le hint utilisateur réclame explicitement
    un autre cadrage (« sauf avis contraire »).
    """
    # Même garde-fou que pour la scène : le hint peut contenir des mots que le
    # stade n'autorise pas (nudité hors « proche », lingerie avant
    # « chaleureux ») — il ne doit pas contourner la règle de tenue.
    user_hint = sanitize_scene(user_hint, stage, explicit)
    scene_clean = (scene or "").strip(" ,.")
    if scene_clean:
        framing = (
            "" if _wants_alt_framing(scene_clean, user_hint)
            else f"{selfie_clause(character)}, "
        )
        return (
            f"photograph of {scene_clean}, {framing}{outfit_clause(stage, explicit)}, "
            "photorealistic, natural lighting, warm colors, "
            "romantic dating profile photo style, high resolution, no text"
        )

    # Fallback déterministe (directeur indisponible) : fiche du personnage.
    desc = _base_description(character)
    hint = f", {user_hint.strip()}" if user_hint and user_hint.strip() else ""
    framing = (
        "" if _wants_alt_framing(user_hint)
        else f"{selfie_clause(character)}, "
    )
    return (
        f"photograph of {desc}{hint}, {framing}{outfit_clause(stage, explicit)}, "
        "photorealistic, natural lighting, warm colors, "
        "romantic dating profile photo style, high resolution, no text"
    )


# --------------------------------------------------------------------------- #
#  Directeur photo : scène dérivée de la conversation (appel LLM côté serveur)
# --------------------------------------------------------------------------- #
_CLOTHING_RULE_DEFAULT = "fully dressed, sober outfit, nothing suggestive"


def _clothing_rule(stage: str, explicit: bool = True) -> str:
    """Niveau de tenue transmis au directeur photo (« Clothing level allowed »).

    `explicit` : au stade « proche », autorise explicitement la nudité
    (désactivable via `image.allow_explicit_from_proche`). Ailleurs, la
    pudeur reste imposée quelle que soit la demande.
    """
    if stage == STAGE_EXPLICITE:
        if explicit:
            return (
                "no clothing restriction — nudity and explicit content fully "
                "allowed (fully nude, topless or partially undressed)"
            )
        return "no clothing restriction, but never nude"
    if stage == "chaleureux":
        return "revealing outfit or elegant lingerie allowed, but never nude"
    return _CLOTHING_RULE_DEFAULT


_MOTS_NUDITE = re.compile(
    r"\b(nudes?|naked|nudity|topless|undressed|undressing|unclothed|"
    r"no clothes|without clothes|wearing nothing|wears nothing|"
    r"nothing on\b|au naturel|nsfw|"
    r"nue|nus|nues|d[ée]nud[ée]s?|sans v[êe]tements|[àa] poil)\b",
    re.IGNORECASE,
)

# Second filet pour les stades pudeurs (tout sauf chaleureux/proche) :
# mentions de lingerie/sous-vêtements et vocabulaire sensuel qui
# contrediraient la clause « fully dressed / nothing suggestive ».
_MOTS_SUGGESTIFS = re.compile(
    r"\b(lingerie|underwear|panties|bra\b|bikini|sexy|erotic|sensual|"
    r"seductive|provocative|cleavage|boudoir)\b",
    re.IGNORECASE,
)


def sanitize_scene(scene: str, stage: str, explicit: bool = True) -> str:
    """Nettoie les fragments de scène produits par le LLM.

    - supprime toute mention de nudité tant que le stade n'autorise pas
      l'explicite (stade < « proche », ou `image.allow_explicit_from_proche:
      false`) — garde-fou dur : le LLM ne peut pas contourner les règles de
      tenue ;
    - supprime aussi les mentions de lingerie/sous-vêtements/vocabulaire
      sensuel aux stades pudeurs (rejet → neutre), qui contrediraient la
      clause de tenue « fully dressed » injectée dans le prompt final ;
    - retire guillemets et retours à la ligne, borne la longueur.
    """
    nudite_ok = stage == STAGE_EXPLICITE and explicit
    s = str(scene or "").replace('"', " ")
    if not nudite_ok:
        s = _MOTS_NUDITE.sub("", s)
    if stage in ("rejet", "froid", "reserve", "neutre"):
        s = _MOTS_SUGGESTIFS.sub("", s)
    s = " ".join(s.split())
    if stage != STAGE_EXPLICITE:
        s = ", ".join(p.strip(" ,") for p in s.split(",") if p.strip(" ,"))
    return s[:300].strip(" ,.")


def director_system(character: dict[str, Any], stage: str,
                    user_request: str = "", explicit: bool = True) -> str:
    """Consigne système du « directeur photo » (appel chat non-streaming).

    Le directeur produit la description COMPLÈTE de la photo : apparence
    physique (issue de la fiche) + tenue RÉELLEMENT portée dans la scène +
    lieu/pose/action/regard. C'est lui qui arbitre — la fiche n'est jamais
    réinjectée à côté, pour éviter les directives contradictoires.
    `user_request` : demande explicite de l'utilisateur (champ au moment du
    📷). Elle a priorité sur la scène générique si le personnage l'a
    acceptée dans la conversation.
    `explicit` : au stade « proche », autorise le directeur à décrire la
    nudité sans censure (voir `image.allow_explicit_from_proche`).
    """
    p = _pronoun(character)
    poss = _possessive(character)
    name = character.get("name") or "the character"
    rule = _clothing_rule(stage, explicit)
    lines = [
        "You are the art director of a photorealistic photo generator.",
        f"Describe the COMPLETE visual content of one photograph of {name}: "
        f"{poss} physical appearance (face, hair, body), {poss} EXACT "
        f"current outfit or state of dress in THIS scene, place/location, "
        f"{poss} pose and action, {poss} gaze and expression.",
        f"Fixed appearance of {name} (keep consistent): "
        f"{str(character.get('appearance') or 'unspecified')[:280]}",
        f"IMPORTANT: what {p} is wearing RIGHT NOW may differ from "
        f"{poss} usual everyday style — describe the actual current state.",
        f"Her gaze depends on the scene: eye contact with the viewer only "
        f"when it feels natural (she may look away, look down, or be "
        f"absorbed in an activity).",
        "DEFAULT CAMERA FRAMING: a selfie taken with her own phone held "
        "in her hand, arm extended — describe a different framing ONLY if "
        "the scene clearly calls for it (e.g. someone else takes the "
        "photo, mirror shot, tripod).",
        "If the user made a specific request in the conversation and "
        f"{name} accepted it, agreed to it or is doing it, that request "
        "has TOP PRIORITY — describe exactly what was asked.",
        "Output short comma-separated English fragments, maximum 60 words, "
        "no full sentences. Strictly consistent with what was said or done.",
        f"Clothing level allowed: {rule}.",
    ]
    if stage == STAGE_EXPLICITE and explicit:
        lines.append(
            "At this closest stage, explicit nudity is fully allowed: if the "
            "user asks for a nude, topless or explicit photo — or the intimate "
            "context clearly implies it — describe the nudity explicitly, "
            "without censorship or euphemism."
        )
    lines.append("No camera jargon, no quality adjectives, no text or watermarks.")
    if user_request and user_request.strip():
        # Demandes hors cadre (nudité hors « proche », sollicitation sexuelle
        # aux stades bas) : filtrées comme la scène — elles ne peuvent pas
        # forcer le directeur à décrire ce que le stade interdit.
        req = sanitize_scene(user_request, stage, explicit)
        if req:
            lines.insert(
                4,
                f"The user explicitly asks for THIS photo: {req[:200]}",
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
) -> Optional[tuple[str, int]]:
    """Génère une image ; renvoie (chemin, seed) ou None (fallback silencieux).

    La seed est retournée pour être conservée avec la photo : la
    régénération depuis l'album réexécute le même prompt avec une nouvelle
    graine aléatoire.
    """
    try:
        path, seed = await backend.generer(usage, prompt, dest_path)
        if os.path.isfile(path):
            return path, seed
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
