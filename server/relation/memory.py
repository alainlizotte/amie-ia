"""Souvenirs sémantiques de la session — embeddings via le serveur llamaembed.

Serveur d'embeddings llama.cpp (`--embedding`, modèle embeddinggemma,
endpoint OpenAI-compatible `/v1/embeddings`). Les souvenirs sont des faits
courts sur l'utilisateur ;
chaque fait est embeddé à l'écriture et stocké dans le profil JSON. Au tour
suivant, la requête utilisateur est embeddée et les k souvenirs les plus
proches (cosinus) sont injectés dans le prompt système.

L'extraction des faits est déclenchée périodiquement côté serveur (un appel
LLM non-streaming à température 0 avec sortie JSON stricte, parsée de façon
défensive) — un échec n'interrompt jamais la conversation.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any, Optional

import httpx

# Préfixes de tâche recommandés pour embeddinggemma.
_DOC_PREFIX = "title: none | text: "
_QUERY_PREFIX = "query: "
_MAX_INPUT_CHARS = 4800


def _clip(text: str) -> str:
    return text[:_MAX_INPUT_CHARS]


class Embedder:
    """Client minimal pour l'endpoint /v1/embeddings d'un serveur llama.cpp."""

    def __init__(self, base_url: str, model: str, api_key: str = "none"):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _embed_batch(self, inputs: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            "/embeddings",
            json={"model": self.model, "input": inputs},
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        # Tri par index pour respecter l'ordre d'entrée.
        data.sort(key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_batch([_DOC_PREFIX + _clip(t) for t in texts])

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed_batch([_QUERY_PREFIX + _clip(text)]))[0]

    async def available(self) -> bool:
        try:
            await self.embed_query("test")
            return True
        except Exception:
            return False


# --------------------------------------------------------------------------- #
#  Similarité cosinus (locale, sans dépendance numpy)
# --------------------------------------------------------------------------- #
def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------- #
#  Magasin de souvenirs (persisté dans le profil JSON)
# --------------------------------------------------------------------------- #
class MemoryStore:
    """Ajout et rappel de souvenirs sémantiques d'une session."""

    def __init__(self, embedder: Optional[Embedder], max_memories: int = 40):
        self.embedder = embedder
        self.max_memories = max_memories

    # ------------------------------------------------------------------ #
    async def add_facts(self, profile: dict[str, Any], facts: list[str]) -> int:
        """Ajoute des faits (embeddés, dédupliqués). Renvoie le nombre ajoutés.

        Fail-safe : si l'embedder est indisponible, les faits sont quand même
        stockés SANS vecteur (rappel par similarité impossible mais texte
        conservé ; ils seront injectés en secours les plus récents).
        """
        facts = [f.strip() for f in facts if isinstance(f, str) and f.strip()]
        if not facts:
            return 0
        existing = {
            _norm_fact(m.get("fact", "")) for m in profile.get("memories", [])
        }
        new_facts = [
            f for f in facts if _norm_fact(f) not in existing
        ]
        if not new_facts:
            return 0

        vectors: list[Optional[list[float]]] = [None] * len(new_facts)
        if self.embedder is not None:
            try:
                vecs = await self.embedder.embed_documents(new_facts)
                vectors = list(vecs)
            except Exception:
                pass  # stockage sans vecteur (fallback)

        memories = profile.setdefault("memories", [])
        ts = datetime.utcnow().isoformat()
        for fact, vec in zip(new_facts, vectors):
            memories.append({"fact": fact[:400], "embedding": vec, "ts": ts})

        # FIFO : on garde les plus récents.
        if len(memories) > self.max_memories:
            profile["memories"] = memories[-self.max_memories:]
        return len(new_facts)

    # ------------------------------------------------------------------ #
    async def retrieve(
        self,
        profile: dict[str, Any],
        query: str,
        top_k: int = 6,
        min_similarity: float = 0.30,
    ) -> list[str]:
        """Rappelle les top_k souvenirs les plus proches de la requête.

        Sans embedder disponible : renvoie les souvenirs les plus récents
        (fallback déterministe, jamais vide si des souvenirs existent).
        """
        memories = profile.get("memories", []) or []
        if not memories:
            return []

        if self.embedder is None:
            return [m["fact"] for m in memories[-top_k:]]

        try:
            qvec = await self.embedder.embed_query(query)
        except Exception:
            return [m["fact"] for m in memories[-top_k:]]

        scored = []
        for m in memories:
            vec = m.get("embedding")
            sim = cosine(qvec, vec) if vec else -1.0
            scored.append((sim, m))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        results = [
            m["fact"] for sim, m in scored[:top_k]
            if sim >= min_similarity and m.get("fact")
        ]
        if not results:
            # Rien de pertinent : fallback sur les 2 plus récents pour que le
            # personnage garde une continuité minimale.
            results = [m["fact"] for m in memories[-2:] if m.get("fact")]
        return results


def _norm_fact(fact: str) -> str:
    """Normalisation légère pour la déduplication."""
    return re.sub(r"\s+", " ", fact.lower().strip())


# --------------------------------------------------------------------------- #
#  Extraction de faits depuis un échange (appel LLM secondaire, défensif)
# --------------------------------------------------------------------------- #
EXTRACTION_PROMPT = (
    "Tu es un module d'extraction. À partir de l'échange suivant entre un "
    "utilisateur et son interlocutrice, extrais UNIQUEMENT les informations "
    "durables que l'utilisateur révèle sur LUI-MÊME (prénom, goûts, travail, "
    "animaux, événements de vie, préférences).\n"
    "Réponds STRICTEMENT par un tableau JSON de chaînes courtes à la 3e "
    "personne (ex: [\"S'appelle Marc\", \"A un chat nommé Rex\"]).\n"
    "Si aucune information nouvelle n'apparaît, réponds exactement : []\n"
    "N'ajoute AUCUN autre texte, AUCUNE explication.\n\n"
    "ÉCHANGE :\n"
)


def parse_facts(raw: str) -> list[str]:
    """Parse défensif de la réponse du modèle → liste de faits propres.

    Cherche le premier '[' et le dernier ']' puis json.loads ; tolère les
    blocs markdown ```json```. Toute erreur renvoie une liste vide.
    """
    if not raw:
        return []
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    facts = []
    for item in data:
        if isinstance(item, str) and item.strip():
            facts.append(item.strip()[:400])
    return facts[:8]
