# Tests de l'arbitrage GPU (server/gpu.py) — exclusion mutuelle
# LLM (tours) ↔ ComfyUI (générations d'images).

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import gpu  # noqa: E402


@pytest.fixture(autouse=True)
def _etat_frais():
    """État neuf par test : la Condition doit être liée à la boucle courante."""
    gpu._cv = asyncio.Condition()
    gpu._turns = 0
    gpu._jobs = 0
    gpu._tour_tasks = set()
    yield


@pytest.mark.asyncio
async def test_comfy_attend_la_fin_du_tour():
    await gpu.turn_begin()
    t = asyncio.create_task(gpu.comfy_begin())
    await asyncio.sleep(0.05)
    assert gpu._jobs == 0  # la génération attend la fin du tour
    await gpu.turn_end()
    await asyncio.wait_for(t, timeout=2)
    assert gpu._jobs == 1
    await gpu.comfy_end()
    assert gpu._jobs == 0


@pytest.mark.asyncio
async def test_tour_attend_les_jobs_comfy():
    await gpu.comfy_begin()
    t = asyncio.create_task(gpu.turn_begin())
    await asyncio.sleep(0.05)
    assert gpu._turns == 0  # le tour attend la fin de la génération
    await gpu.comfy_end()
    await asyncio.wait_for(t, timeout=2)
    assert gpu._turns == 1
    await gpu.turn_end()
    assert gpu._turns == 0


@pytest.mark.asyncio
async def test_reentrance_generation_dans_le_tour():
    # Photo d'initiative : générée PAR la tâche qui porte le tour —
    # elle ne doit PAS s'attendre elle-même.
    await gpu.turn_begin()
    await asyncio.wait_for(gpu.comfy_begin(), timeout=1)
    assert gpu._turns == 1 and gpu._jobs == 1
    await gpu.comfy_end()
    assert await gpu.turn_end() is True


@pytest.mark.asyncio
async def test_tour_end_true_uniquement_pour_le_dernier_tour():
    await gpu.turn_begin()
    await gpu.turn_begin()
    assert await gpu.turn_end() is False
    assert await gpu.turn_end() is True
    assert gpu.turns_actifs() == 0


@pytest.mark.asyncio
async def test_garde_fous_temporels():
    # ComfyUI hangé : le tour démarre quand même après le timeout.
    await gpu.comfy_begin()
    await asyncio.wait_for(gpu.turn_begin(timeout_comfy=0.05), timeout=2)
    assert gpu._turns == 1
    await gpu.comfy_end()
    await gpu.turn_end()
    # Conversation interminable : la génération part quand même après le
    # timeout (et le tour qui se termine la réveille plus tôt).
    await gpu.turn_begin()
    await asyncio.wait_for(gpu.comfy_begin(timeout_llm=0.05), timeout=2)
    assert gpu._jobs == 1
    await gpu.comfy_end()
    await gpu.turn_end()
