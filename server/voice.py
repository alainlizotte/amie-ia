"""Messages vocaux du personnage — de vrais audios, à la place du texte.

Comme sur une vraie messagerie : PARFOIS (probabilité par réponse, stade
« chaleureux » requis), le personnage envoie un message VOCAL — une bulle
audio à écouter, jamais un texte à lire. Le texte reste dans l'historique
du LLM (contexte), mais seul l'audio atteint le fil.

Backend : **edge-tts** (voix neurales Microsoft, qualité proche d'un vrai
vocal) — requiert Internet au moment de la synthèse. La synthèse locale
(Piper) pourra s'ajouter comme backend alternatif.

Gating (déterministe, `vocal_prevu`) : option utilisateur activée + stade
« chaleureux »/« proche » + tirage < `voice.chance_per_reply`.
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any, Optional

# Voix neurales par défaut — québécoises d'abord (cohérence avec le ton de
# l'app), substituables via la config (voice.voice_femme / voice_homme).
VOIX_PAR_DEFAUT = {
    "femme": "fr-CA-SylvieNeural",
    "homme": "fr-CA-AntoineNeural",
}

STAGES_VOCAUX = ("chaleureux", "proche")


# --------------------------------------------------------------------------- #
#  Décision déterministe (appelée AVANT la génération du tour)
# --------------------------------------------------------------------------- #
def vocal_prevu(
    profile: dict[str, Any],
    options_voix: bool,
    stage: str,
    cfg_voice: Any,
) -> bool:
    """True si la réponse de CE tour doit être un message vocal.

    Gating : option du profil activée + stade « chaleureux »/« proche » +
    tirage < chance_per_reply. Décidé avant la génération pour pouvoir
    désactiver le streaming texte de ce tour (le vocal REMPLACE le texte).
    """
    if cfg_voice is None or not getattr(cfg_voice, "enabled", False):
        return False
    if not options_voix:
        return False
    if stage not in STAGES_VOCAUX:
        return False
    chance = float(getattr(cfg_voice, "chance_per_reply", 0.25) or 0.0)
    return random.random() < chance


# --------------------------------------------------------------------------- #
#  Nettoyage du texte pour la synthèse (markdown, emojis, URLs)
# --------------------------------------------------------------------------- #
_EMOJIS_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u2B00-\u2BFF\u20E3]"
)


def nettoyer_pour_voix(texte: str, max_chars: int = 450) -> str:
    """Prépare un texto pour la synthèse : markdown/emojis/URLs retirés,
    coupé sur une fin de phrase."""
    t = str(texte or "")
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)
    t = re.sub(r"[*_`~>#|]", " ", t)
    t = _EMOJIS_RE.sub(" ", t)
    t = re.sub(r"https?:\S+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    if len(t) > max_chars:
        coupe = t[:max_chars]
        for sep in (". ", " !", " ?", "…", "!", "?", ".", ","):
            i = coupe.rfind(sep)
            if i > max_chars // 2:
                return coupe[: i + len(sep)].strip()
        return coupe.strip()
    return t


def estimer_duree(texte: str) -> int:
    """Durée approximative du vocal en secondes (~2,6 mots/s en français)."""
    mots = len((texte or "").split())
    return max(1, round(mots / 2.6))


# --------------------------------------------------------------------------- #
#  Synthèse (edge-tts, async)
# --------------------------------------------------------------------------- #
def _reglage(profil_voix: Optional[dict[str, Any]]) -> tuple[str, str]:
    """Traduit le profil vocal (pitch/rate 1.0 neutre) en arguments edge-tts."""
    rate = float((profil_voix or {}).get("rate", 1.0) or 1.0)
    pitch = float((profil_voix or {}).get("pitch", 1.0) or 1.0)
    rate_pct = int(round((rate - 1.0) * 100))
    pitch_hz = int(round((pitch - 1.0) * 15))
    return f"{rate_pct:+d}%", f"{pitch_hz:+d}Hz"


async def generer_vocal(
    sid: str,
    texte: str,
    profil_voix: Optional[dict[str, Any]],
    dest_path: Path,
    cfg_voice: Any,
) -> Optional[tuple[int, str]]:
    """Synthétise un vocal → fichier MP3. Renvoie (durée_s, texte_nettoyé).

    Renvoie None si le backend échoue (l'appelant retombe sur le texte).
    """
    try:
        import edge_tts  # import paresseux : dépendance optionnelle
    except ImportError:
        return None

    net = nettoyer_pour_voix(
        texte, max_chars=int(getattr(cfg_voice, "max_chars", 450) or 450)
    )
    if len(net) < 10:
        return None

    genre = str((profil_voix or {}).get("genre", "femme"))
    voix = str(
        getattr(cfg_voice, "voice_femme", None) if genre == "femme"
        else getattr(cfg_voice, "voice_homme", None)
    ) or VOIX_PAR_DEFAUT.get(genre, VOIX_PAR_DEFAUT["femme"])
    rate, pitch = _reglage(profil_voix)

    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(net, voix, rate=rate, pitch=pitch)
        await communicate.save(str(dest_path))
    except Exception:  # noqa: BLE001 — réseau/voix absente : repli texte
        return None
    if not dest_path.is_file():
        return None
    return estimer_duree(net), net
