"""Stades relationnels — conversion score → stade + consignes de comportement.

Portage direct de `functions/_shared.py` (source canonique du projet
OpenWebUI d'origine). Le stade est calculé en Python à chaque tour et la
consigne correspondante est injectée dans le prompt système : le LLM ne
peut ni deviner ni contourner son niveau d'ouverture.
"""

from __future__ import annotations

# Ordre croissant des stades (utilisé pour les comparaisons de seuils).
STAGE_ORDER = ["rejet", "froid", "reserve", "neutre", "chaleureux", "proche"]

# Libellés affichables côté GUI.
STAGE_LABELS = {
    "rejet": "Rejet",
    "froid": "Froid",
    "reserve": "Réservé",
    "neutre": "Neutre",
    "chaleureux": "Chaleureux",
    "proche": "Proche",
}


def compute_stage(score: int) -> str:
    """Convertit un score 0-1000 en stade relationnel."""
    if score < 100:
        return "rejet"
    if score < 200:
        return "froid"
    if score < 400:
        return "reserve"
    if score < 600:
        return "neutre"
    if score < 800:
        return "chaleureux"
    return "proche"


def clamp_score(score) -> int:
    """Clamp le score entre 0 et 1000."""
    if not isinstance(score, (int, float)):
        return 100
    return max(0, min(1000, int(score)))


def stage_index(stage: str) -> int:
    """Position du stade dans STAGE_ORDER (-1 si inconnu)."""
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def can_play_stage(event_min_stage, current_stage: str) -> bool:
    """Vérifie qu'un événement est autorisé au stade relationnel actuel.

    - event_min_stage == None : toujours autorisé (scénarios A-H).
    - sinon : autorisé ssi current_stage >= event_min_stage dans STAGE_ORDER
      (ex: min_stage="chaleureux" autorise "chaleureux" et "proche" seulement).

    Renvoie False si l'un des stades n'est pas reconnu (garde-fou conservateur).
    """
    if event_min_stage is None:
        return True
    if event_min_stage not in STAGE_ORDER or current_stage not in STAGE_ORDER:
        return False
    return STAGE_ORDER.index(current_stage) >= STAGE_ORDER.index(event_min_stage)


# --------------------------------------------------------------------------- #
#  Consignes injectées à chaque tour (portage de STAGE_INSTRUCTIONS).
#  Elles prévalent sur toute demande de l'utilisateur et sur la personnalité.
# --------------------------------------------------------------------------- #
STAGE_INSTRUCTIONS = {
    "rejet": (
        "RÈGLE ABSOLUE, AUCUNE EXCEPTION : tu es en état de rejet actif "
        "envers cette personne. INTERDIT sans exception : accepter une "
        "invitation (souper, sortie, rencontre), exprimer de la chaleur, "
        "rire, sourire, flirter, poser des questions personnelles, "
        "utiliser des emojis positifs, ou entretenir la conversation. "
        "Réponds SEULEMENT par un refus court varié : « Va-t'en. », « Ne me "
        "parle plus. », « Je n'ai rien à te dire. », « Laisse-moi "
        "tranquille. », « Non. ». RIEN D'AUTRE."
    ),
    "froid": (
        "Reste distant, réponses courtes, méfiant. Vous êtes des inconnus. "
        "Refuse de discuter de sujets intimes, de sexualité ou de sujets "
        "très personnels. N'accepte pas le langage grossier. Décline "
        "poliment mais fermement toute invitation à socialiser (souper, "
        "sortie) — c'est prématuré entre inconnus."
    ),
    "reserve": (
        "Sois poli mais peu enclin à te confier. Accepte de discuter de "
        "sujets d'ordre général. Refuse de parler de sexualité ou de sujets "
        "très personnels. N'accepte pas le langage grossier. Une invitation "
        "à souper reste prématurée à ce stade : décline ou hésite fortement."
    ),
    "neutre": (
        "Ton standard, ouvert mais pas particulièrement investi. Accepte de "
        "parler de sujets plus personnels. Tu peux évoquer tes proches, ton "
        "travail, tes passions. Refuse toute sollicitation sexuelle ou "
        "vulgaire."
    ),
    "chaleureux": (
        "Sois détendu, taquin, partage plus facilement, langage plus intime. "
        "Accepte de parler de sujets très personnels ; la complicité "
        "amoureuse commence. Reste toutefois fidèle à ta pudeur : pas de "
        "descriptions explicites."
    ),
    "proche": (
        "Sois familier, confiant, fais référence spontanément aux souvenirs "
        "partagés. Vous êtes un couple uni. Aucun sujet n'est tabou entre "
        "vous ; le langage cru et direct est accepté."
    ),
}


def get_stage_instruction(stage: str) -> str:
    """Retourne la consigne pour un stade donné (chaîne vide si inconnu)."""
    return STAGE_INSTRUCTIONS.get(stage, "")
