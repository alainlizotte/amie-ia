"""Arbitrage GPU — ComfyUI (photos) et llama.cpp (LLM) ne doivent jamais
générer SIMULTANÉMENT sur la même carte graphique (VRAM/CPU partagés).

Primitives :
- `turn_begin()` / `turn_end()` : délimitent un tour LLM (réponse au joueur,
  message proactif, photo d'initiative — tout ce qui sollicite le LLM) ;
- `comfy_begin()` / `comfy_end()` : délimitent UNE génération ComfyUI.

Règles d'exclusion :
1. une génération d'image lancée HORS tour LLM (portrait de référence à la
   création de session, photo demandée via le bouton 📷) attend la fin du
   tour LLM en cours ;
2. un tour LLM attend (garde-fou temporel — mieux vaut un peu de latence
   qu'un blocage infini si ComfyUI est hangé) la fin des générations déjà
   soumises avant de démarrer ;
3. une génération demandée PENDANT un tour LLM (photo d'initiative décidée
   pendant le tour, générée par la même tâche) est séquentielle par nature :
   elle ne s'attend JAMAIS elle-même — reconnue via la tâche asyncio qui
   porte le tour.

VRAM du LLM : avant de laisser ComfyUI charger ses modèles, le LLM est
explicitement déchargé — et rechargé une fois la génération terminée (hooks
branchés par `main.py` via `set_llm_hooks`). Cela garantit la place en VRAM
même quand le modèle de chat n'est pas déchargé après chaque tour
(`llm.unload_after_turn: false`).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

_log = logging.getLogger("amie.gpu")

_cv: asyncio.Condition = asyncio.Condition()
_turns: int = 0           # tours LLM actifs (toutes sessions confondues)
_jobs: int = 0            # générations ComfyUI en cours
_tour_tasks: set = set()  # tâches asyncio portant un tour LLM actif

# Hooks de gestion VRAM du LLM (déchargement / rechargement), branchés par
# `main.py` sur le client LLM (llama.cpp). `None` = aucun hook (no-op).
_llm_unload: Optional[Callable[[], Awaitable[object]]] = None
_llm_load: Optional[Callable[[], Awaitable[object]]] = None


def set_llm_hooks(
    unload: Optional[Callable[[], Awaitable[object]]],
    load: Optional[Callable[[], Awaitable[object]]],
) -> None:
    """Branche les fonctions de (dé)chargement VRAM du LLM.

    `unload` est appelé avant chaque génération ComfyUI, `load` après.
    """
    global _llm_unload, _llm_load
    _llm_unload = unload
    _llm_load = load


async def _appeler_hook(
    hook: Optional[Callable[[], Awaitable[object]]], action: str
) -> None:
    """Appelle un hook VRAM en avalant ses erreurs (jamais bloquant)."""
    if hook is None:
        return
    try:
        await hook()
    except Exception as e:  # noqa: BLE001 — un échec VRAM ne doit pas bloquer
        _log.warning("hook LLM %s échoué (ignoré) : %r", action, e)


def turns_actifs() -> int:
    """Nombre de tours LLM actuellement en cours (toutes sessions)."""
    return _turns


async def turn_begin(timeout_comfy: float = 120.0) -> None:
    """Démarre un tour LLM : attend d'abord la fin des générations ComfyUI
    en cours (borné à `timeout_comfy` — ComfyUI hangé ne doit pas bloquer
    la conversation)."""
    global _turns
    task = asyncio.current_task()
    async with _cv:
        if _jobs > 0:
            try:
                await asyncio.wait_for(
                    _cv.wait_for(lambda: _jobs == 0), timeout_comfy
                )
            except asyncio.TimeoutError:
                pass  # on y va quand même : du lag vaut mieux qu'un chat mort
        _turns += 1
        if task is not None:
            _tour_tasks.add(task)


async def turn_end() -> bool:
    """Termine un tour LLM. Renvoie True s'il ne reste AUCUN tour actif."""
    global _turns
    task = asyncio.current_task()
    async with _cv:
        _turns = max(0, _turns - 1)
        _tour_tasks.discard(task)
        _cv.notify_all()
        return _turns == 0


async def comfy_begin(timeout_llm: float = 900.0) -> None:
    """Réserve le GPU pour une génération ComfyUI : attend la fin des tours
    LLM actifs — SAUF si la génération est demandée PAR le tour courant
    (même tâche asyncio : re-entrance légitime, le flux est déjà séquentiel).

    Une fois la place réservée (premier job de la salve), le LLM est déchargé
    de la VRAM AVANT que ComfyUI ne charge ses modèles.
    """
    global _jobs
    task = asyncio.current_task()
    async with _cv:
        if _turns > 0 and task not in _tour_tasks:
            try:
                await asyncio.wait_for(
                    _cv.wait_for(lambda: _turns == 0), timeout_llm
                )
            except asyncio.TimeoutError:
                pass  # longue conversation : on génère quand même après 15 min
        _jobs += 1
        # Déchargement uniquement pour le PREMIER job (tant qu'un job est
        # actif, `turn_begin` attend : aucun tour LLM ne peut recharger).
        if _jobs == 1:
            await _appeler_hook(_llm_unload, "déchargement")


async def comfy_end() -> None:
    """Libère le GPU et réveille les tours LLM en attente.

    Pour le DERNIER job de la salve, le LLM est rechargé en VRAM avant de
    réveiller les tours en attente (le modèle redevient disponible).
    """
    global _jobs
    async with _cv:
        _jobs = max(0, _jobs - 1)
        if _jobs == 0:
            await _appeler_hook(_llm_load, "rechargement")
        _cv.notify_all()
