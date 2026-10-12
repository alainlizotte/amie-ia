"""Intégration ComfyUI — génération d'images (portraits et photos).

Soumission d'un workflow JSON
(format API) via `POST /prompt`, polling `GET /history/{id}`, téléchargement
du PNG via `GET /view`. Deux usages :
- « portrait » : photo de référence du personnage (création de session) ;
- « photo »    : photos supplémentaires demandées pendant la session.

Les deux usages partagent le graphe de génération **Qwen Image 2.1 Turbo**
(texte → image). Un export d'édition (image → image) est conservé dans le
dossier `workflows/` pour un usage futur (voir `USAGE_WORKFLOWS`).
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

# Workflow ComfyUI utilisé pour chaque usage. Les deux usages pointent vers
# le graphe de génération Qwen Image 2.1 Turbo (texte → image) ; il suffit de
# changer cette table pour basculer un usage sur un autre export (ex. le
# workflow d'édition « image_qwen_image_2_1_image_edit_api.json »).
USAGE_WORKFLOWS: dict[str, str] = {
    "portrait": "image_qwen_image_2_1_api.json",
    "photo": "image_qwen_image_2_1_api.json",
}

# Classes de nœuds d'encodage texte reconnues par le patching : l'ancien
# `CLIPTextEncode` (clé `text`) et le nouveau `TextEncodeQwenImage21` de
# Qwen Image 2.1 (clé `prompt`).
PROMPT_CLASSES = ("CLIPTextEncode", "TextEncodeQwenImage21")
PROMPT_KEYS = ("text", "prompt")

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
        candidats: list[str] = []
        mappe = USAGE_WORKFLOWS.get(usage)
        if mappe:
            candidats.append(mappe)
        # Repli : convention historique `<usage>.json` / `<usage>.api.json`
        # (aussi utilisée par les tests qui installent leur propre graphe).
        candidats += [f"{usage}.json", f"{usage}.api.json"]
        for name in candidats:
            p = os.path.join(self._workflows_dir, name)
            if os.path.isfile(p):
                # utf-8-sig : tolère un BOM éventuel (éditeurs Windows).
                with open(p, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
        raise ComfyUIError(
            f"Aucun workflow ComfyUI trouvé pour l'usage '{usage}'. "
            f"Attendu un fichier dans {self._workflows_dir}/ "
            f"({mappe or usage + '.json'}, format API exporté depuis ComfyUI)."
        )

    @staticmethod
    def _find_prompt_node(graph: dict[str, Any], usage: str) -> Optional[str]:
        """Clé du nœud d'encodage du prompt positif (convention + heuristique)."""
        for k in graph:
            if k.upper().endswith("_PROMPT_NODE") and k.startswith(usage.upper()):
                return k
        for k in graph:
            if k.upper().endswith("_PROMPT_NODE"):
                return k
        for k, v in graph.items():
            if not isinstance(v, dict):
                continue
            ct = str(v.get("class_type") or "")
            inputs = v.get("inputs")
            if not isinstance(inputs, dict):
                continue
            reconnu = ct in PROMPT_CLASSES or (
                "TextEncode" in ct and "QwenImage" in ct
            )
            if reconnu:
                for key in PROMPT_KEYS:
                    if key in inputs:
                        return k
        return None

    @staticmethod
    def _find_seed_node(graph: dict[str, Any], usage: str) -> Optional[str]:
        """Clé du nœud portant la seed (convention + sampler prioritaire)."""
        for k in graph:
            if k.upper().endswith("_SEED_NODE") and k.startswith(usage.upper()):
                return k
        for k in graph:
            if k.upper().endswith("_SEED_NODE"):
                return k
        # Priorité au sampler (KSampler…) plutôt qu'à un nœud annexe qui
        # exposerait aussi une clé `seed`.
        for k, v in graph.items():
            if not isinstance(v, dict):
                continue
            ct = str(v.get("class_type") or "")
            inputs = v.get("inputs")
            if "Sampler" in ct and isinstance(inputs, dict) and "seed" in inputs:
                return k
        for k, v in graph.items():
            if (
                isinstance(v, dict)
                and isinstance(v.get("inputs"), dict)
                and "seed" in v["inputs"]
            ):
                return k
        return None

    def _patch_workflow(
        self,
        graph: dict[str, Any],
        prompt_text: str,
        usage: str,
        seed: Optional[int] = None,
    ) -> tuple[dict[str, Any], int]:
        """Injecte le prompt texte et une seed dans le graphe (convention
        `<USAGE>_PROMPT_NODE` / `<USAGE>_SEED_NODE`, avec heuristiques
        adaptées à Qwen Image 2.1)."""
        if seed is None:
            seed = random.randint(0, 2**31 - 1)
        graph = json.loads(json.dumps(graph))  # deep copie

        prompt_node_key = self._find_prompt_node(graph, usage)
        if prompt_node_key is not None:
            inputs = graph[prompt_node_key].setdefault("inputs", {})
            # `text` (CLIPTextEncode) ou `prompt` (TextEncodeQwenImage21).
            key = "text" if "text" in inputs else "prompt"
            inputs[key] = prompt_text

        seed_node_key = self._find_seed_node(graph, usage)
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
