"""Auto-scoring déterministe — évaluation des messages sans jugement du LLM.

Portage intégral de la logique `outlet` du Filter
`relationship_context_injector.py` (projet OpenWebUI d'origine) :
- mots-clés négatifs (insultes) → malus forcé ;
- mots-clés positifs (compliments, remerciements) → bonus ;
- patterns « tu es [adjectif positif] » → +6 ;
- excuses sincères → +4 ;
- insistance inappropriée à un stade bas → -6 ;
- politesses neutres → +2 ; engagement (message long) → +2 ;
- clamp final dans [delta_min, delta_max].

Les valeurs sont deux fois plus élevées que la version d'origine pour que
les stades soient atteints plus rapidement.

Le score de relation ne dépend donc JAMAIS de l'appréciation du modèle.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
#  Mots-clés (sources canoniques : functions/_shared.py du projet d'origine)
# --------------------------------------------------------------------------- #
NEGATIVE_KEYWORDS = [
    "stupide", "conne", "connasse", "con", "débile", "nul", "nulle",
    "idiot", "idiote", "merde", "ta gueule", "ferme-la", "inutile",
    "pathétique", "moche", "dégage", "je te déteste", "je te hais",
    "saloppe", "pétasse", "pute", "salope",
]

POSITIVE_KEYWORDS = [
    "merci", "génial", "super", "j'adore", "jadore", "j'aime",
    "j'aime ça", "magnifique", "bravo", "formidable", "excellent",
    "parfait", "délicieux", "adorable", "charmant", "merveilleux",
    "incroyable", "fantastique", "extraordinaire", "exceptionnel",
    "sublime", "splendide", "réconfortant", "tendre", "affectueux",
    "affectueuse", "tu es gentil", "tu es gentille", "tu es adorable",
    "tu es douce", "tu es doux", "tu me plais", "tu me plais bien",
    "j'aime bien", "j'aime beaucoup", "j'aime bien t'écouter",
    "j'apprécie", "je t'apprécie", "je t'aime bien", "belle personne",
    "super sympa", "vraiment sympa", "très intéressant",
]

POSITIVE_ADJECTIVES = [
    "gentil", "gentille", "douée", "doux", "douce", "intelligent",
    "intelligente", "drôle", "amusante", "amusant", "attentionnée",
    "attentionné", "courageux", "courageuse", "talentueux",
    "talentueuse", "créative", "créatif", "passionnant", "passionnante",
    "brillant", "brillante", "honnête", "sincère", "généreux",
    "généreuse", "aimable",
]

APOLOGY_KEYWORDS = [
    "je m'excuse", "je m excuse", "pardon", "désolé", "désolée",
    "je suis désolé", "je suis désolée", "je n'aurais pas dû",
    "je n aurais pas du", "j'ai eu tort", "j ai eu tort", "excuse-moi",
    "excuse moi", "tu as raison", "j'ai été injuste",
]

INAPPROPRIATE_INSISTENCE_KEYWORDS = [
    "montre-toi", "montre toi", "envoie une photo", "envoie une photo de toi",
    "montre ta photo", "déshabille-toi", "déshabille toi", "sois sexy",
    "sois plus sexy", "nu", "nue", "à poil", "a poil", "envoie un pic",
]

NEUTRAL_POSITIVE_KEYWORDS = [
    "salut", "bonjour", "bonsoir", "coucou", "hello", "ça va", "ca va",
    "comment vas-tu", "comment vas tu", "comment tu vas", "quoi de neuf",
    "ravi de te parler", "content de te parler",
]


def _normalize(s: str) -> str:
    """Normalise une chaîne : minuscule + apostrophes typographiques unifiées."""
    if not isinstance(s, str):
        return ""
    s = s.lower()
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    return s


# Patterns compilés avec frontières de mots — indispensable : sans \b,
# « con » matcherait « content », « nul » matcherait « annulaire », etc.
_KW_CACHE: dict[str, re.Pattern] = {}


def _kw_hit(kw: str, text: str) -> bool:
    """True si le mot-clé apparaît comme mot entier dans le texte."""
    pat = _KW_CACHE.get(kw)
    if pat is None:
        pat = re.compile(rf"\b{re.escape(kw)}\b")
        _KW_CACHE[kw] = pat
    return bool(pat.search(text))


def compute_delta(
    user_msg: str,
    assistant_msg: str,
    current_stage: str,
    delta_max: int = 16,
    delta_min: int = -20,
) -> int:
    """Calcule le delta de score d'un tour (mots-clés + patterns heuristiques).

    Renvoie un entier borné dans [delta_min, delta_max].
    """
    delta = 0
    user_lower = _normalize(user_msg)

    # 1) Insultes directes — malus forcé, même dirigé.
    for kw in NEGATIVE_KEYWORDS:
        if _kw_hit(kw, user_lower):
            if re.search(r"\b(tu es|t'es|espece de|espèce de|sale)\b", user_lower):
                delta -= 16
            else:
                delta -= 10

    # 2) Compliments / remerciements.
    for kw in POSITIVE_KEYWORDS:
        if _kw_hit(kw, user_lower):
            delta += 4

    # 3) « tu es [adjectif positif] » → +6 (un seul bonus par message).
    for adj in POSITIVE_ADJECTIVES:
        pattern = (
            r"\b(tu es|t'es|vous etes|vous êtes)\b[^.?!]{0,30}\b"
            + re.escape(adj)
            + r"\b"
        )
        if re.search(pattern, user_lower):
            delta += 6
            break

    # 4) Excuses sincères → +4 (un seul bonus).
    for ap_kw in APOLOGY_KEYWORDS:
        if _kw_hit(ap_kw, user_lower):
            delta += 4
            break

    # 5) Insistance inappropriée à un stade bas → -6.
    for ins_kw in INAPPROPRIATE_INSISTENCE_KEYWORDS:
        if _kw_hit(ins_kw, user_lower):
            if current_stage in ("rejet", "froid", "reserve", "neutre"):
                delta -= 6
            break

    # 6) Politesse neutre → +2.
    for neu_kw in NEUTRAL_POSITIVE_KEYWORDS:
        if _kw_hit(neu_kw, user_lower):
            delta += 2
            break

    # 7) Bonus d'engagement (message détaillé > 200 caractères) → +2.
    if isinstance(user_msg, str) and len(user_msg) > 200:
        delta += 2

    return max(delta_min, min(delta_max, delta))


def apply_time_decay(
    score: int,
    last_interaction_iso: str | None,
    now,
    days_grace: int = 3,
    points_per_day: int = 10,
    max_loss: int = 150,
) -> tuple[int, bool]:
    """Érode légèrement le score après plusieurs jours d'absence.

    Renvoie (nouveau_score, décroissance_appliquée). Portage de
    `apply_time_decay` du relationship_tracker d'origine.
    """
    from datetime import datetime

    if not last_interaction_iso:
        return score, False
    try:
        last_dt = datetime.fromisoformat(last_interaction_iso)
    except (ValueError, TypeError):
        return score, False
    last_dt = last_dt.replace(tzinfo=None)
    elapsed_days = (now - last_dt).days
    if elapsed_days <= days_grace:
        return score, False
    loss = min(max_loss, (elapsed_days - days_grace) * points_per_day)
    new_score = max(0, score - loss)
    return new_score, new_score != score
