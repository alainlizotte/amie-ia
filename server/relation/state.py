"""Profil relationnel persistant d'une session — `data/session_<id>.json`.

Équivalent du `PartyState` du projet D&D : écritures atomiques
(tempfile + os.replace), schéma par défaut, helpers de mise à jour.
Chaque session appartient à un utilisateur (meta.user) et porte :
- le personnage (preset ou custom),
- le score / stade de relation,
- l'historique des scénarios consommés,
- les souvenirs (avec embeddings),
- le registre des photos (album).
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .stages import compute_stage

SCHEMA_SESSION: dict[str, Any] = {
    "meta": {
        "user": "",
        "session_id": "",
        "titre": "",
        "date_creation": "",
        "date_maj": "",
    },
    "character": {},
    "user_info": {"name": "", "preferences": ""},
    "relationship_score": 100,
    "relationship_stage": "froid",
    "interaction_count": 0,
    "last_interaction": None,
    "event_history": [],
    "event_attempts": {},
    "last_event_at": None,
    "last_injected_event_id": None,
    "memories": [],          # [{fact, embedding, ts}]
    "photos": [],            # [{file, kind, caption, ts}]
}


class RelationState:
    """Lecture/écriture atomique du profil d'une session."""

    def __init__(self, data_dir: str, session_id: str):
        self.data_dir = Path(data_dir)
        self.session_id = session_id
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self.data_dir / f"session_{self.session_id}.json"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos" / self.session_id

    # ------------------------------------------------------------------ #
    def exists(self) -> bool:
        """True si le fichier de session est présent sur disque."""
        return self.path.is_file()

    def load(self) -> dict[str, Any]:
        """Charge le profil ; renvoie un profil neuf si absent."""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # Fusion défensive : complète les clés manquantes du schéma.
                merged = copy.deepcopy(SCHEMA_SESSION)
                merged.update(data)
                for k, v in SCHEMA_SESSION.items():
                    if isinstance(v, dict) and k in merged:
                        base = dict(v)
                        base.update(merged[k] or {})
                        merged[k] = base
                return merged
            return copy.deepcopy(SCHEMA_SESSION)
        except FileNotFoundError:
            fresh = copy.deepcopy(SCHEMA_SESSION)
            fresh.setdefault("meta", {})["session_id"] = self.session_id
            return fresh
        except (json.JSONDecodeError, OSError) as e:
            return {"_erreur": str(e)}

    def save(self, profile: dict[str, Any]) -> Optional[str]:
        """Écriture atomique. Renvoie un message d'erreur ou None si ok."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        profile.setdefault("meta", {})["date_maj"] = datetime.now().isoformat()
        fd, tmp = tempfile.mkstemp(
            dir=str(self.data_dir), prefix=".session_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(profile, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return f"Erreur écriture : {e}"
        return None

    def delete(self) -> bool:
        """Supprime le profil et les photos associées."""
        deleted = False
        try:
            self.path.unlink()
            deleted = True
        except FileNotFoundError:
            pass
        except OSError:
            pass
        try:
            import shutil
            if self.photos_dir.is_dir():
                shutil.rmtree(self.photos_dir, ignore_errors=True)
        except OSError:
            pass
        return deleted

    # ------------------------------------------------------------------ #
    #  Helpers métier
    # ------------------------------------------------------------------ #
    def set_score(self, profile: dict[str, Any], new_score: int,
                  mark_interaction: bool = True) -> None:
        """Applique un score clampé + recalcule le stade (+ compteur d'interactions)."""
        from .stages import clamp_score
        new_score = clamp_score(new_score)
        profile["relationship_score"] = new_score
        profile["relationship_stage"] = compute_stage(new_score)
        if mark_interaction:
            cnt = profile.get("interaction_count", 0) or 0
            profile["interaction_count"] = int(cnt) + 1
            profile["last_interaction"] = datetime.utcnow().isoformat()

    def add_photo(self, profile: dict[str, Any], file: str, kind: str,
                  caption: str) -> None:
        """Enregistre une photo dans l'album (remplace si le fichier existe déjà)."""
        photos = profile.setdefault("photos", [])
        photos[:] = [p for p in photos if p.get("file") != file]
        photos.append({
            "file": file,
            "kind": kind,
            "caption": caption,
            "ts": datetime.now().isoformat(),
        })

    def photo_url(self, file: str) -> str:
        """URL publique d'une photo de la session (montage /data)."""
        from urllib.parse import quote
        return f"/data/photos/{quote(self.session_id)}/{quote(file)}"
