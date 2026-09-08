"""Profil utilisateur « dating app » — la fiche de L'humain derrière l'écran.

L'utilisateur remplit son propre profil selon les MÊMES catégories que les
personnages IA (prénom, âge, apparence, personnalité, métier, centres
d'intérêt, histoire, situation amoureuse, recherches). La fiche est injectée
dans le prompt système : le personnage sait AVEC QUI il parle et peut s'y
référer naturellement, comme un vrai match qui a lu le profil.

Stockage (dans le data_dir du projet) :
- Fiches : `profils_utilisateurs.json` — map clé_utilisateur → profil.
- Photo  : `profils_photos/<clé>.<ext>` — uploadée par l'utilisateur ;
  analysée par le modèle vision (mmproj chargé par llama.cpp) et la
  description générée est rangée dans le champ `photo_description`.

Toutes les écritures sont atomiques (tmp + os.replace), comme le reste du
projet. Seuls les champs de la liste blanche `CHAMPS` sont persistés.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

# Catégories du profil — mêmes catégories que la fiche des personnages IA.
CHAMPS: tuple[str, ...] = (
    "name",               # prénom
    "age",                # âge
    "gender",             # genre ("F" / "H")
    "title",              # surnom / accroche (ex. « L'aventurier tranquille »)
    "occupation",         # métier / études
    "interests",          # centres d'intérêt
    "appearance",         # apparence (saisie manuellement si pas de photo)
    "personality",        # personnalité
    "histoire",           # histoire personnelle / bio
    "parcours_amoureux",  # situation amoureuse
    "preferences",        # ce que la personne recherche
)

# Champs techniques (non éditables directement par l'utilisateur).
_CHAMPS_TECH = ("photo", "photo_description", "photo_erreur", "date_modification")

# Extensions photo acceptées + taille max (~8 Mo de binaire).
_EXTENSIONS_PHOTO = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}
_TAILLE_MAX = 9 * 1024 * 1024


def _profils_path(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / "profils_utilisateurs.json"


def _photos_dir(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / "profils_photos"


def cle_utilisateur(nom: str) -> str:
    """Clé de stockage dérivée du nom de compte (sûre pour un nom de fichier)."""
    return re.sub(r"[^a-z0-9_-]", "", (nom or "").strip().lower()) or "inconnu"


def _charger_tous(data_dir: str | os.PathLike) -> dict[str, dict[str, Any]]:
    try:
        with open(_profils_path(data_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _sauver_tous(data_dir: str | os.PathLike, profils: dict[str, dict[str, Any]]) -> None:
    path = _profils_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profils, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def charger_profil(data_dir: str | os.PathLike, nom: str) -> dict[str, Any]:
    """Profil de l'utilisateur (dict vide si jamais rempli)."""
    return _charger_tous(data_dir).get(cle_utilisateur(nom), {})


def sauver_profil(data_dir: str | os.PathLike, nom: str, champs: dict[str, Any]) -> dict[str, Any]:
    """Fusionne les champs autorisés et persiste. Renvoie le profil.

    Champs autorisés : `CHAMPS` (éditables) + champs techniques
    (`photo_description`, `photo_erreur` — écrits par l'analyse vision).
    `date_modification` est toujours mis à jour automatiquement.
    """
    autorises = set(CHAMPS) | {"photo_description", "photo_erreur"}
    profils = _charger_tous(data_dir)
    cle = cle_utilisateur(nom)
    profil = profils.get(cle, {})
    for k in autorises:
        if k in champs:
            v = champs[k]
            profil[k] = (str(v).strip() if isinstance(v, str) else v)
    from datetime import datetime
    profil["date_modification"] = datetime.now().isoformat()
    profils[cle] = profil
    _sauver_tous(data_dir, profils)
    return profil


def purger_analyse_photo(data_dir: str | os.PathLike, nom: str) -> None:
    """Efface description + erreur (nouvelle photo en attente d'analyse)."""
    profils = _charger_tous(data_dir)
    cle = cle_utilisateur(nom)
    profil = profils.get(cle)
    if not profil:
        return
    profil.pop("photo_description", None)
    profil.pop("photo_erreur", None)
    profils[cle] = profil
    _sauver_tous(data_dir, profils)


def photo_path(data_dir: str | os.PathLike, nom: str) -> Path | None:
    """Chemin de la photo de profil uploadée (None si absente)."""
    d = _photos_dir(data_dir)
    if not d.is_dir():
        return None
    cle = cle_utilisateur(nom)
    for ext in _EXTENSIONS_PHOTO:
        p = d / f"{cle}.{ext}"
        if p.is_file():
            return p
    return None


def sauver_photo(data_dir: str | os.PathLike, nom: str, data_url: str) -> tuple[Path, str]:
    """Décode une data-URL base64 et enregistre la photo.

    Renvoie (chemin, type_mime). Lève ValueError si format/taille invalides.
    """
    m = re.match(r"^data:(image/(?:png|jpe?g|webp));base64,(.+)$", (data_url or "").strip(), re.DOTALL)
    if not m:
        raise ValueError("Format d'image non reconnu (png, jpg ou webp attendu).")
    mime, b64 = m.group(1), m.group(2)
    try:
        brut = base64.b64decode(b64, validate=True)
    except Exception as e:  # noqa: BLE001
        raise ValueError("Image base64 invalide.") from e
    if not brut:
        raise ValueError("Image vide.")
    if len(brut) > _TAILLE_MAX:
        raise ValueError("Image trop volumineuse (max ~8 Mo).")
    ext = "jpg" if mime in ("image/jpeg",) else mime.split("/", 1)[1]
    d = _photos_dir(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    # Nettoie toute ancienne photo sous une autre extension.
    cle = cle_utilisateur(nom)
    for e in _EXTENSIONS_PHOTO:
        ancien = d / f"{cle}.{e}"
        if ancien.is_file():
            try:
                ancien.unlink()
            except OSError:
                pass
    dest = d / f"{cle}.{ext}"
    tmp = str(dest) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(brut)
    os.replace(tmp, dest)
    return dest, mime
