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


def get_backend(
    base_url: str = "",
    timeout_total: int = 300,
    workflows: Optional[dict[str, str]] = None,
) -> Optional[ComfyUIBackend]:
    """Renvoie un backend ComfyUI prêt à l'emploi, ou None si désactivé.

    `workflows` : table usage → fichier de workflow (config image.workflow /
    image.workflow_edit — chaque installation peut pointer ses variantes
    locales, ex. NSFW avec LoRA).
    """
    try:
        return ComfyUIBackend(
            base_url=base_url, timeout_total=timeout_total, workflows=workflows,
        )
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
# le selfie par défaut n'est PAS imposé (« sauf avis contraire »). La liste
# couvre les formulations courantes d'un appareil POSÉ à distance (téléphone
# sur une table, posé sur une table de nuit, filmé de l'autre bout de la
# pièce…) et pas seulement les prises par un tiers.
_FRAMING_HINT_RE = re.compile(
    r"\b(selfie|mirror|miroir|point of view|pov|taken by|held by|"
    r"photographer|someone else|stranger|passer-?by|tripod|"
    r"holding the camera|photobooth|prise par|prise de vue|"
    r"photographe|quelqu.un d.autre|appareil sur pied|"
    r"camera (?:on|set|placed|resting|propped|positioned|left|sitting|pointed|aimed)|"
    r"phone (?:on|set|placed|resting|propped|positioned|left|leaning|sitting)|"
    r"(?:propped|resting|leaning|placed|positioned|set) (?:up )?(?:on|against|by|near)|"
    r"on (?:a |the |his |her |its )?(?:table|desk|nightstand|dresser|shelf|"
    r"counter|windowsill|bedside|floor|chair|sofa|couch)|"
    r"(?:filmed|recorded|shot|captured) (?:from|by)|from across|"
    r"across the (?:room|bed|table)|distance shot|wide shot|"
    r"full[- ](?:body|frame) shot|seen from|viewed from|framed from|"
    r"webcam|hands?-?free)\b",
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


# Traits d'apparence attendus dans une scène du directeur photo (cheveux,
# yeux, silhouette…). Une scène qui n'en mentionne AUCUN ne verrouille pas
# l'identité du personnage → on retombe sur le prompt avec la fiche complète
# (sinon les photos sortent sans cheveux/yeux — personnage méconnaissable).
_APPARENCE_RE = re.compile(
    r"\b(hair|eyes|brunette|blonde|redhead|bald|curl\w*|braid\w*|ponytail|"
    r"chignon|beard|mustache|freckle\w*|skin|tall|petite|platinum|"
    r"auburn|brun\w*|chatain\w*|rousse?|blond\w*)\b",
    re.IGNORECASE,
)


def _scene_decrit_apparence(scene: str) -> bool:
    """True si la scène décrit au moins un trait physique (cheveux, yeux…)."""
    return bool(_APPARENCE_RE.search(scene or ""))


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

    Quand la scène existe ET décrit l'apparence (cheveux/yeux — ancres
    d'identité), elle fait foi SEULE pour l'apparence/la tenue : la fiche
    du personnage n'est PAS réinjectée (son style quotidien — « elle porte
    des robes fluides » — contredirait une scène où elle est nue ou
    autrement habillée, et noierait le modèle d'image sous des directives
    contradictoires). Si la scène ne décrit PAS l'apparence, la fiche
    COMPLÈTE est réinjectée : mieux vaut un léger risque de contradiction
    de tenue qu'un personnage méconnaissable. La clause de tenue du stade
    reste systématiquement ajoutée en garde-fou.

    Cadrage par défaut : SELFIE (téléphone tenu dans sa main, bras tendu)
    — imposé sauf si la scène ou le hint utilisateur réclame explicitement
    un autre cadrage (« sauf avis contraire »).
    """
    # Même garde-fou que pour la scène : le hint peut contenir des mots que le
    # stade n'autorise pas (nudité hors « proche », lingerie avant
    # « chaleureux ») — il ne doit pas contourner la règle de tenue.
    user_hint = sanitize_scene(user_hint, stage, explicit)
    scene_clean = (scene or "").strip(" ,.")
    if scene_clean and _scene_decrit_apparence(scene_clean):
        framing = (
            "" if _wants_alt_framing(scene_clean, user_hint)
            else f"{selfie_clause(character)}, "
        )
        return (
            f"photograph of {scene_clean}, {framing}{outfit_clause(stage, explicit)}, "
            "photorealistic, natural lighting, warm colors, "
            "romantic dating profile photo style, high resolution, no text"
        )

    # Fallback déterministe (directeur indisponible OU scène sans apparence) :
    # fiche du personnage + scène/hint comme contexte.
    desc = _base_description(character)
    fragments = [user_hint.strip(), scene_clean]
    contexte = ", ".join(f for f in fragments if f)
    hint = f", {contexte}" if contexte else ""
    framing = (
        "" if _wants_alt_framing(scene_clean, user_hint)
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
        "MANDATORY IDENTITY ANCHORS: ALWAYS start your description with "
        f"{name}'s HAIR (color, length, style) and visible facial features "
        "(eyes, face) — every photo must be recognizably the same person.",
        f"IMPORTANT: what {p} is wearing RIGHT NOW may differ from "
        f"{poss} usual everyday style — describe the actual current state.",
        f"Her gaze depends on the scene: eye contact with the viewer only "
        f"when it feels natural (she may look away, look down, or be "
        f"absorbed in an activity).",
        "DEFAULT CAMERA FRAMING: a selfie taken with her own phone held "
        "in her hand, arm extended — keep it UNLESS the scene clearly "
        "calls for something else.",
        "WHEN THE FRAMING IS NOT A SELFIE, make it EXPLICIT and "
        "unmistakable in the description: say where the camera/phone is "
        "(e.g. 'phone propped on the nightstand, filmed from across the "
        "bed') or WHO takes the photo (e.g. 'photo taken by a passerby'). "
        "The framing written in the description is what the generator "
        "follows.",
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


async def generer_image_edit(
    backend: ComfyUIBackend,
    prompt: str,
    ref_path: Optional[str],
    dest_path: str,
) -> Optional[tuple[str, int]]:
    """Édition d'une image de référence (usage « photo_edit ») — photo
    souvenir d'un rendez-vous. `ref_path` None ou échec → None (l'appelant
    retombe sur la génération solo)."""
    if not ref_path:
        return None
    try:
        path, seed = await backend.generer(
            "photo_edit", prompt, dest_path, ref_path=ref_path,
        )
        if os.path.isfile(path):
            return path, seed
    except ComfyUIError as e:
        _log.warning("[image] échec édition souvenir : %s", e)
    except Exception as e:  # noqa: BLE001
        _log.warning("[image] erreur inattendue en édition : %r", e)
    return None


def caption_for(kind: str, stage: str, character_name: str) -> str:
    """Légende FR affichée sous la photo dans l'album."""
    labels = {
        "portrait": f"Photo de profil de {character_name}",
        "photo": f"Photo partagée ({stage})",
    }
    return labels.get(kind, "Photo")


# --------------------------------------------------------------------------- #
#  Photo souvenir d'un rendez-vous — le joueur à côté du personnage.
#
#  Mode ÉDITION (image → image) : la photo de profil du JOUEUR sert de
#  canevas (identité préservée par le modèle d'édition) et le personnage —
#  décrit par sa fiche — est ajouté à ses côtés dans la scène du rendez-vous.
#  Les garde-fous de tenue par stade restent imposés (outfit_clause +
#  sanitize), comme pour toute photo.
# --------------------------------------------------------------------------- #
def _genre_joueur(genre: str) -> str:
    """« F » → femme, « H »/« M » → homme (le profil joueur accepte H ou M)."""
    return "femme" if (genre or "").upper().startswith("F") else "homme"


def souvenir_edit_prompt(
    character: dict[str, Any],
    stage: str,
    scene: str,
    user_description: str = "",
    user_gender: str = "",
    explicit: bool = True,
) -> str:
    """Instruction d'ÉDITION : ajouter le personnage à côté du joueur.

    `scene` : fragments visuels du rendez-vous (directeur photo, déjà
    sanitizés). `user_description` : description de l'apparence du joueur
    (analyse vision de sa photo de profil) — renforce la cohérence,
    l'identité étant déjà ancrée par l'image de référence.
    """
    scene_clean = sanitize_scene(scene, stage, explicit)
    desc_user = " ".join(str(user_description or "").split())[:220]
    name = character.get("name") or "the character"
    genre_perso = "woman" if (character.get("gender") or "F").upper() == "F" else "man"
    desc_perso = _base_description(character)
    genre_j = _genre_joueur(user_gender)

    fragments = [
        f"photograph of the same {genre_j} from the input photo, "
        "keep identity exactly unchanged",
    ]
    if desc_user:
        fragments.append(f"({desc_user})")
    fragments.append(
        f"now together with {name}, a {genre_perso} matching this "
        f"description: {desc_perso}"
    )
    if scene_clean:
        fragments.append(scene_clean)
    fragments.append(
        "side by side, close together, smiling naturally at each other, "
        "candid couple photo taken by a passerby, half-body framing, "
        "warm natural lighting"
    )
    fragments.append(outfit_clause(stage, explicit))
    fragments.append("photorealistic, high resolution, no text")
    return ", ".join(f for f in fragments if f)


def souvenir_solo_prompt(
    character: dict[str, Any],
    stage: str,
    scene: str,
    explicit: bool = True,
) -> str:
    """Prompt de repli (pas de photo joueur / échec d'édition) : photo SOLO
    du personnage dans la scène du rendez-vous — cadrage pris par un tiers."""
    scene_clean = sanitize_scene(scene, stage, explicit)
    desc = _base_description(character)
    return (
        f"photograph of {desc}"
        + (f", {scene_clean}" if scene_clean else "")
        + ", candid photo taken by a passerby, half-body framing, "
        f"{outfit_clause(stage, explicit)}, photorealistic, natural lighting, "
        "warm colors, high resolution, no text"
    )


MSG_PENDING_SOUVENIR = "📸 Photo souvenir du rendez-vous en cours de création…"
