"""Auto-scoring déterministe — évaluation des messages sans jugement du LLM.

Portage intégral de la logique `outlet` du Filter
`relationship_context_injector.py` (projet OpenWebUI d'origine) :
- mots-clés négatifs (insultes) → malus forcé (inchangé) ;
- mots-clés positifs (compliments, remerciements) → +6 ;
- patterns « tu es [adjectif positif] » → +8 ;
- excuses sincères → +6 ;
- insistance inappropriée à un stade bas → -6 (inchangé) ;
- politesses neutres → +3 ; engagement (message long) → +3 ;
- message neutre (aucun signal détecté) → +1 — une conversation ordinaire
  ne doit JAMAIS laisser le score inchangé ;
- clamp final dans [delta_min, delta_max].

Le score de relation ne dépend donc JAMAIS de l'appréciation du modèle.
"""

from __future__ import annotations

import re
import unicodedata

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


def _sans_accents(s: str) -> str:
    """Retire les diacritiques (« génial » → « genial ») après normalisation.

    Permet un appariement insensible aux accents dans les deux sens : un
    joueur qui écrit « genial », « desole » ou « nulle » sans accents est
    évalué comme s'il avait écrit les mots accentués du barème.
    """
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


# Patterns compilés avec frontières de mots — indispensable : sans \b,
# « con » matcherait « content », « nul » matcherait « annulaire », etc.
_KW_CACHE: dict[str, re.Pattern] = {}


def _kw_hit(kw: str, text: str) -> bool:
    """True si le mot-clé apparaît comme mot entier dans le texte.

    L'appariement est insensible aux accents : le mot-clé et le texte sont
    comparés sans diacritiques (le pattern est compilé une seule fois).
    """
    pat = _KW_CACHE.get(kw)
    if pat is None:
        pat = re.compile(rf"\b{re.escape(_sans_accents(kw))}\b")
        _KW_CACHE[kw] = pat
    return bool(pat.search(_sans_accents(text)))


def compute_delta(
    user_msg: str,
    assistant_msg: str,
    current_stage: str,
    delta_max: int = 16,
    delta_min: int = -20,
    gain_multiplier: float = 1.0,
) -> int:
    """Calcule le delta de score d'un tour (mots-clés + patterns heuristiques).

    `gain_multiplier` multiplie TOUS les points du barème, positifs comme
    négatifs — 1.5 = barème +50 % dans les deux sens (gains ET malus),
    passages de stades ~50 % plus rapides à mécanique de punition égale.
    Chaque valeur est arrondie au plus proche, puis le delta est borné à
    [delta_min ; delta_max] : avec un multiplicateur > 1, delta_min et
    delta_max doivent être élargis proportionnellement dans la config
    (ex : 1.5 → [-30 ; +24]) sinon les extrêmes seraient rognés.

    Logique négative préservée quel que soit le multiplicateur :
    - un message comportant au moins un malus (delta < 0) n'est JAMAIS
      rattrapé par le plancher (le plancher ne s'applique qu'à delta == 0) ;
    - les malus restent dominants : -24 (insulte dirigée ×1.5) l'emporte sur
      un compliment simultané (+9) — l'insulte punit toujours plus que le
      compliment ne récompense, exactement comme en barème de base.

    Renvoie un entier borné dans [delta_min, delta_max].
    """
    try:
        m = max(0.0, float(gain_multiplier))
    except (TypeError, ValueError):
        m = 1.0

    def _pts(v: int) -> int:
        # Arrondi au plus proche (round() ferait du banker's rounding).
        return int(v * m + 0.5) if v >= 0 else -int(-v * m + 0.5)

    delta = 0
    user_lower = _normalize(user_msg)

    # 1) Insultes directes — malus forcé, même dirigé.
    for kw in NEGATIVE_KEYWORDS:
        if _kw_hit(kw, user_lower):
            if re.search(r"\b(tu es|t'es|espece de|espèce de|sale)\b", user_lower):
                delta += _pts(-16)
            else:
                delta += _pts(-10)

    # 2) Compliments / remerciements.
    for kw in POSITIVE_KEYWORDS:
        if _kw_hit(kw, user_lower):
            delta += _pts(6)

    # 3) « tu es [adjectif positif] » → +8 de base (un seul bonus par message).
    #    Comparaison sans accents : « t'es vraiment douee » matche « douée ».
    user_na = _sans_accents(user_lower)
    for adj in POSITIVE_ADJECTIVES:
        pattern = (
            r"\b(tu es|t'es|vous etes|vous êtes)\b[^.?!]{0,30}\b"
            + re.escape(_sans_accents(adj))
            + r"\b"
        )
        if re.search(pattern, user_na):
            delta += _pts(8)
            break

    # 4) Excuses sincères → +6 de base (un seul bonus).
    for ap_kw in APOLOGY_KEYWORDS:
        if _kw_hit(ap_kw, user_lower):
            delta += _pts(6)
            break

    # 5) Insistance inappropriée à un stade bas → -6 de base.
    for ins_kw in INAPPROPRIATE_INSISTENCE_KEYWORDS:
        if _kw_hit(ins_kw, user_lower):
            if current_stage in ("rejet", "froid", "reserve", "neutre"):
                delta += _pts(-6)
            break

    # 6) Politesse neutre → +3 de base.
    for neu_kw in NEUTRAL_POSITIVE_KEYWORDS:
        if _kw_hit(neu_kw, user_lower):
            delta += _pts(3)
            break

    # 7) Bonus d'engagement (message détaillé > 200 caractères) → +3 de base.
    if isinstance(user_msg, str) and len(user_msg) > 200:
        delta += _pts(3)

    # 8) Filet « message neutre » : une conversation ordinaire (aucun mot-clé
    #    positif ni négatif, delta resté exactement à 0) fait progresser la
    #    relation d'au moins 1 point de base — discuter reste un signe
    #    d'intérêt. Un delta NÉGATIF (insulte, insistance) n'est JAMAIS
    #    rattrapé, même partiellement compensé par un compliment.
    if delta == 0:
        delta = _pts(1)

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
