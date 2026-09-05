"""Intégration ComfyUI — génération d'images (portraits et photos).

Soumission d'un workflow JSON
(format API) via `POST /prompt`, polling `GET /history/{id}`, téléchargement
du PNG via `GET /view`. Deux usages :
- « portrait » : photo de référence du personnage (création de session) ;
- « photo »    : photos supplémentaires demandées pendant la session.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import Any, Optional

import httpx

from .. import gpu as _gpu

USAGES_VALIDES = {"portrait", "photo"}

DEFAULT_TIMEOUT_TOTAL = 300
POLL_INTERVAL = 3.0


class ComfyUIError(Exception):
    """Erreur lors de la soumission / l'attente d'un workflow ComfyUI."""


class ComfyUIBackend:
    """Cliente HTTP légère pour soumettre un workflow ComfyUI et récupérer le PNG."""

    def __init__(self, base_url: str = "", timeout_total: int = DEFAULT_TIMEOUT_TOTAL):
        self.base_url = (
            base_url
            or os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
        ).rstrip("/")
        self.timeout_total = timeout_total
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=60.0)
        self._workflows_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "workflows"
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    def _load_workflow(self, usage: str) -> dict[str, Any]:
        for name in (f"{usage}.json", f"{usage}.api.json"):
            p = os.path.join(self._workflows_dir, name)
            if os.path.isfile(p):
                # utf-8-sig : tolère un BOM éventuel (éditeurs Windows).
                with open(p, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
        raise ComfyUIError(
            f"Aucun workflow ComfyUI trouvé pour l'usage '{usage}'. "
            f"Attendu un fichier dans {self._workflows_dir}/{usage}.json "
            f"(format API, exporté depuis ComfyUI)."
        )

    def _patch_workflow(
        self,
        graph: dict[str, Any],
        prompt_text: str,
        usage: str,
        seed: Optional[int] = None,
    ) -> tuple[dict[str, Any], int]:
        """Injecte le prompt texte et une seed dans le graphe (convention
        `<USAGE>_PROMPT_NODE` / `<USAGE>_SEED_NODE`, avec heuristiques)."""
        if seed is None:
            seed = random.randint(0, 2**31 - 1)
        graph = json.loads(json.dumps(graph))  # deep copie

        prompt_node_key = None
        for k in graph:
            if k.upper().endswith("_PROMPT_NODE") and k.startswith(usage.upper()):
                prompt_node_key = k
                break
        if prompt_node_key is None:
            for k in graph:
                if k.upper().endswith("_PROMPT_NODE"):
                    prompt_node_key = k
                    break
        if prompt_node_key is None:
            for k, v in graph.items():
                if (
                    isinstance(v, dict)
                    and v.get("class_type") == "CLIPTextEncode"
                    and isinstance(v.get("inputs", {}).get("text"), str)
                ):
                    prompt_node_key = k
                    break
        if prompt_node_key is not None:
            graph[prompt_node_key]["inputs"]["text"] = prompt_text

        seed_node_key = None
        for k in graph:
            if k.upper().endswith("_SEED_NODE") and k.startswith(usage.upper()):
                seed_node_key = k
                break
        if seed_node_key is None:
            for k in graph:
                if k.upper().endswith("_SEED_NODE"):
                    seed_node_key = k
                    break
        if seed_node_key is None:
            for k, v in graph.items():
                if (
                    isinstance(v, dict)
                    and isinstance(v.get("inputs"), dict)
                    and "seed" in v["inputs"]
                ):
                    seed_node_key = k
                    break
        if seed_node_key is not None:
            graph[seed_node_key]["inputs"]["seed"] = int(seed)

        return graph, seed

    async def _submit_prompt(self, graph: dict[str, Any], client_id: str = "amie") -> str:
        payload = {"prompt": graph, "client_id": client_id}
        try:
            r = await self._client.post("/prompt", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ComfyUIError(f"Échec POST /prompt : {e}") from e
        data = r.json()
        if "prompt_id" not in data:
            raise ComfyUIError(f"Réponse ComfyUI inattendue (pas de prompt_id) : {data}")
        return data["prompt_id"]

    async def _poll_history(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout_total
        while time.time() < deadline:
            try:
                r = await self._client.get(f"/history/{prompt_id}")
                r.raise_for_status()
            except httpx.HTTPError:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            data = r.json()
            entry = data.get(prompt_id)
            if entry:
                return entry
            await asyncio.sleep(POLL_INTERVAL)
        raise ComfyUIError(
            f"Timeout en attendant la fin de la génération (>{self.timeout_total}s)."
        )

    async def _download_png(self, history_entry: dict[str, Any], dest_path: str) -> str:
        outputs = history_entry.get("outputs") or {}
        for node_id, payload in outputs.items():
            images = payload.get("images") or []
            if not images:
                continue
            first = images[0]
            params = {
                "filename": first["filename"],
                "subfolder": first.get("subfolder", "") or "",
                "type": first.get("type", "output") or "output",
            }
            try:
                r = await self._client.get("/view", params=params)
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise ComfyUIError(
                    f"Échec téléchargement image ComfyUI ({params['filename']}) : {e}"
                )
            with open(dest_path, "wb") as f:
                f.write(r.content)
            return dest_path
        raise ComfyUIError(
            "Aucune image de sortie trouvée dans l'historique ComfyUI."
        )

    async def generer(
        self,
        usage: str,
        prompt_text: str,
        dest_path: str,
        seed: Optional[int] = None,
    ) -> tuple[str, int]:
        """Génère une image via ComfyUI et l'écrit dans `dest_path`."""
        if usage not in USAGES_VALIDES:
            raise ComfyUIError(f"Usage '{usage}' inconnu. Validés : {sorted(USAGES_VALIDES)}.")
        graph = self._load_workflow(usage)
        graph, seed = self._patch_workflow(graph, prompt_text, usage, seed)
        # Arbitrage GPU : attend la fin du tour LLM en cours (une soumission
        # ComfyUI ne doit JAMAIS chevaucher une requête llama.cpp). Une
        # génération portée par le tour LLM lui-même (photo d'initiative)
        # passe sans attendre — elle est déjà séquentielle.
        await _gpu.comfy_begin()
        try:
            prompt_id = await self._submit_prompt(graph)
            entry = await self._poll_history(prompt_id)
            await self._download_png(entry, dest_path)
        finally:
            await _gpu.comfy_end()
        return dest_path, seed

    async def dispo(self) -> bool:
        try:
            r = await self._client.get("/system_stats")
            return r.status_code == 200
        except httpx.HTTPError:
            return False
