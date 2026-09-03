"""Génère en lot les portraits de référence des personnages PRÉDÉFINIS.

Utilise exactement le même pipeline que le jeu :
- le personnage est hydraté via `presets.build_character_from_preset`
  (même bloc `character` que celui stocké au profil d'une session) ;
- le prompt vient de `image.helpers.portrait_prompt` (aucun LLM : le portrait
  est déterministe côté serveur) ;
- la génération passe par ComfyUI (workflow `portrait.json`).

Les PNG sont écrits dans le cache PARTAGÉ `data/preset_portraits/<id>.png`
— précisément les fichiers que `_generate_portrait` (server/main.py) copie
vers une nouvelle session au lieu de rappeler ComfyUI. Générer le lot une
fois rend donc le début de chaque discussion instantané (plus d'attente de
portrait).

Seuls les portraits participent au cache : les photos de scène dépendent de
la conversation et ne sont JAMAIS réutilisées d'une session à l'autre.

Usage :
    python scripts/generer_portraits_presets.py [--preset <id>] [--force]

Le script saute les portraits déjà présents (reprise sûre), génère un
portrait même seul (`--preset`), et peut régénérer bêtement le cache
(`--force`). Seed déterministe par personnage : re-runs = résultats stables.
"""

from __future__ import annotations

import asyncio
import argparse
import os
import re
import sys
import zlib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Console Windows (cp1252) : sortie UTF-8 pour les accents dans les logs.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from server.config import get_config  # noqa: E402
from server.image.comfyui import ComfyUIBackend, ComfyUIError  # noqa: E402
from server.image import helpers as img_helpers  # noqa: E402
from server.relation import presets as P  # noqa: E402

_CACHE_DIRNAME = "preset_portraits"


def _cache_path(data_dir: Path, preset_id: str) -> Path | None:
    """Même logique de cache que `_preset_portrait_cache` dans server/main.py."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "", str(preset_id)).strip()
    if not clean:
        return None
    return data_dir / _CACHE_DIRNAME / f"{clean}.png"


def _seed_for(preset_id: str) -> int:
    """Seed stable par personnage (évite l'aléatoire d'un run à l'autre)."""
    return zlib.crc32(str(preset_id).encode("utf-8")) & 0x7FFFFFFF


async def _generer_un(
    backend: ComfyUIBackend,
    preset: dict,
    character: dict,
    dest: Path,
    force: bool = False,
) -> str | None:
    """Génère le portrait d'UN personnage dans `dest` (atomique).

    Renvoie un message d'erreur (ou None si tout est ok). Le fichier est
    d'abord écrit sous un nom temporaire puis déplacé : un cache jamais
    à moitié écrit (un PNG tronqué ne doit pas passer pour un cache valide).
    """
    prompt = img_helpers.portrait_prompt(character)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    try:
        await backend.generer("portrait", prompt, str(tmp), seed=_seed_for(preset.get("id", "")))
        if not tmp.is_file() or tmp.stat().st_size == 0:
            return "fichier temporaire vide"
        os.replace(tmp, dest)
    except ComfyUIError as e:
        return f"ComfyUI : {e}"
    except Exception as e:                          # noqa: BLE001
        return f"erreur inattendue : {e!r}"
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return None


async def _main(args: argparse.Namespace) -> int:
    cfg = get_config()
    data_dir = cfg.abs(cfg.paths.data_dir)

    presets = P.load_preset_characters()
    if not presets:
        print("Aucun personnage prédéfini trouvé dans characters.json.")
        return 1

    if args.preset:
        presets = [p for p in presets if p.get("id") == args.preset]
        if not presets:
            print(f"Personnage '{args.preset}' introuvable.")
            return 1

    backend = ComfyUIBackend(
        base_url=cfg.image.base_url,
        timeout_total=cfg.image.timeout_total,
    )
    print(f"ComfyUI : {backend.base_url}")
    if not await backend.dispo():
        print("ComfyUI injoignable — abandon.")
        await backend.aclose()
        return 1

    nb_total = len(presets)
    nb_gen = 0
    nb_skip = 0
    echecs: list[str] = []
    try:
        for i, preset in enumerate(presets, start=1):
            preset_id = preset.get("id", "")
            cache = _cache_path(data_dir, preset_id)
            if cache is None:
                echecs.append(f"{preset_id} : id non éligible au cache")
                print(f"[{i}/{nb_total}] {preset_id} : SKIP (id non éligible)")
                continue

            if cache.is_file() and cache.stat().st_size > 0 and not args.force:
                nb_skip += 1
                print(f"[{i}/{nb_total}] {preset_id} : déjà en cache — réutilisé.")
                continue

            character = P.build_character_from_preset(preset)
            print(f"[{i}/{nb_total}] {preset_id} : génération en cours…",
                  flush=True)
            err = await _generer_un(backend, preset, character, cache, args.force)
            if err is not None:
                echecs.append(f"{preset_id} : {err}")
                print(f"    ** ECHEC : {err}")
                continue
            nb_gen += 1
            print(f"    ** OK : {cache.name} ({cache.stat().st_size // 1024} Ko)")
    finally:
        await backend.aclose()

    print()
    print(f"Terminé : {nb_gen} généré(s), {nb_skip} déjà en cache, "
          f"{len(echecs)} échec(s) sur {nb_total} personnage(s).")
    if echecs:
        for e in echecs:
            print(f"  - {e}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pré-génère les portraits des personnages prédéfinis "
                    "dans le cache partagé data/preset_portraits/.",
    )
    parser.add_argument("--preset", help="id d'un personnage seul (ex: maya_lin)")
    parser.add_argument("--force", action="store_true",
                        help="régénère même si le cache existe déjà")
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())