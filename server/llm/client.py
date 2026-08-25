"""Client LLM — endpoint OpenAI-compatible (llama.cpp / Ollama).

Appels non-streaming et
streaming SSE, strip des blocs thinking Gemma 4, chargement/déchargement
du modèle en VRAM (router llama.cpp) avec retry sur HTTP 500 pour survivre
à la contention VRAM avec ComfyUI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from ..config import LLMConfig

_log = logging.getLogger("amie.llm.client")


# --------------------------------------------------------------------------- #
#  Thinking stripping (Gemma 4 utilise <|channel>thought...<channel|>)
# --------------------------------------------------------------------------- #
_THINK_RE = re.compile(r"<\|channel>thought\b.*?<channel\|>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Supprime les blocs de réflexion Gemma 4 du texte de réponse."""
    if not text:
        return text
    return _THINK_RE.sub("", text).strip()


def _safe_split(buf: str) -> tuple[str, str]:
    """Détecte un éventuel début de tag thinking en fin de buffer.

    Renvoie (texte_sûre, reste_à_analyser).
    """
    markers = ("<|channel>tho", "<|channel>th", "<|channel>", "<|chan", "<|ch", "<|c", "<|")
    for m in markers:
        if buf.endswith(m):
            safe = buf[: -len(m)]
            return safe, buf[-len(m):]
    return buf, ""


# --------------------------------------------------------------------------- #
#  Modèles de messages
# --------------------------------------------------------------------------- #
@dataclass
class Message:
    role: str                   # "system" | "user" | "assistant"
    content: str = ""

    def to_openai(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatResult:
    content: str
    finish_reason: str
    raw: dict[str, Any]


# --------------------------------------------------------------------------- #
#  Client
# --------------------------------------------------------------------------- #
class LLMClient:
    """Client léger pour l'endpoint OpenAI-compatible."""

    def __init__(self, config: LLMConfig):
        self.cfg = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(180.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    async def chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
    ) -> ChatResult:
        """Appel non-streaming (utilisé pour l'extraction de souvenirs)."""
        await self.ensure_model_loaded()
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature if temperature is not None else self.cfg.temperature,
            "top_p": self.cfg.top_p,
            "stream": False,
        }
        if self.cfg.options:
            payload["options"] = dict(self.cfg.options)

        delays = (0, 3.0, 8.0)
        last_exc: Exception | None = None
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                await asyncio.sleep(delay)
                await self.ensure_model_loaded()
            try:
                resp = await self._client.post("/chat/completions", json=payload)
                if resp.status_code != 500:
                    break
                _log.warning("chat 500 (tentative %d/%d)", attempt, len(delays))
                last_exc = None
            except httpx.RequestError as e:
                last_exc = e
                _log.warning("chat réseau erreur (tentative %d/%d): %s", attempt, len(delays), e)
        else:
            if last_exc:
                raise last_exc
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})
        content = _strip_thinking(msg.get("content", "") or "")
        return ChatResult(
            content=content,
            finish_reason=choice.get("finish_reason", "stop"),
            raw=data,
        )

    # ------------------------------------------------------------------ #
    async def stream_chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
    ) -> AsyncIterator[str]:
        """Streaming SSE — yield les delta-tokens au fur et à mesure."""
        await self.ensure_model_loaded()
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature if temperature is not None else self.cfg.temperature,
            "top_p": self.cfg.top_p,
            "stream": True,
        }
        if self.cfg.options:
            payload["options"] = dict(self.cfg.options)

        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            think_buf = ""
            in_think = False
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk_str = line[len("data:"):].strip()
                if chunk_str == "[DONE]":
                    return
                try:
                    chunk = json.loads(chunk_str)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content") or ""
                    if not content:
                        continue
                    think_buf += content
                    if in_think:
                        idx = think_buf.find("<channel|>")
                        if idx >= 0:
                            in_think = False
                            think_buf = think_buf[idx + len("<channel|>"):]
                        continue
                    think_idx = think_buf.find("<|channel>thought")
                    if think_idx >= 0:
                        in_think = True
                        before = think_buf[:think_idx]
                        think_buf = think_buf[think_idx:]
                        if before:
                            yield before
                        continue
                    safe, think_buf = _safe_split(think_buf)
                    if safe:
                        yield safe

    # ------------------------------------------------------------------ #
    async def unload_model(self) -> bool:
        """Décharge le modèle de la VRAM (libère la place pour ComfyUI).

        - Ollama : `POST /api/generate` avec `keep_alive: 0`
        - llama.cpp : `POST /models/unload` (router mode)
        """
        if self.cfg.backend == "llamacpp":
            return await self._llamacpp_unload()
        return await self._ollama_unload()

    async def ensure_model_loaded(self) -> bool:
        """S'assure que le modèle est chargé en VRAM (utile après un unload)."""
        if self.cfg.backend == "llamacpp":
            return await self._llamacpp_load()
        return True

    # ------------------------------------------------------------------ #
    async def _ollama_unload(self) -> bool:
        native_base = (
            self.cfg.base_url.rsplit("/v1", 1)[0]
            if self.cfg.base_url.endswith("/v1") else self.cfg.base_url
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as tmp:
                r = await tmp.post(
                    f"{native_base.rstrip('/')}/api/generate",
                    json={"model": self.cfg.model, "keep_alive": 0},
                )
                ok = r.status_code == 200
                if ok:
                    _log.info("ollama model unloaded: %s", self.cfg.model)
                return ok
        except Exception as e:
            _log.warning("ollama unload error: %s", e)
            return False

    async def _llamacpp_unload(self) -> bool:
        root = (
            self.cfg.base_url.rsplit("/v1", 1)[0]
            if self.cfg.base_url.endswith("/v1") else self.cfg.base_url
        )
        try:
            async with httpx.AsyncClient(timeout=15.0) as tmp:
                r = await tmp.post(
                    f"{root.rstrip('/')}/models/unload",
                    json={"model": self.cfg.model},
                )
                if r.status_code == 200:
                    _log.info("llamacpp model unloaded: %s", self.cfg.model)
                    return True
                if r.status_code == 400 and "not running" in r.text:
                    return True
                _log.warning("llamacpp unload failed (%s): %s", r.status_code, r.text[:200])
                return False
        except Exception as e:
            _log.warning("llamacpp unload error: %s", e)
            return False

    async def _llamacpp_load(self) -> bool:
        root = (
            self.cfg.base_url.rsplit("/v1", 1)[0]
            if self.cfg.base_url.endswith("/v1") else self.cfg.base_url
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as tmp:
                r = await tmp.post(
                    f"{root.rstrip('/')}/models/load",
                    json={"model": self.cfg.model},
                )
                if r.status_code == 200:
                    _log.info("llamacpp model loaded: %s", self.cfg.model)
                    return True
                if r.status_code == 400 and (
                    "already loaded" in r.text.lower()
                    or "already running" in r.text.lower()
                ):
                    return True
                if r.status_code == 400 and "already loading" in r.text.lower():
                    return await self._llamacpp_wait_loaded(root, timeout=60.0)
                _log.warning("llamacpp load failed (%s): %s", r.status_code, r.text[:200])
                return False
        except Exception as e:
            _log.warning("llamacpp load error: %s", e)
            return False

    async def _llamacpp_wait_loaded(self, root: str, timeout: float = 60.0) -> bool:
        """Poll /v1/models jusqu'à ce que le modèle cible soit « loaded »."""
        import time
        deadline = time.monotonic() + timeout
        interval = 1.5
        while time.monotonic() < deadline:
            try:
                async with httpx.AsyncClient(timeout=10.0) as tmp:
                    r = await tmp.get(f"{root.rstrip('/')}/v1/models")
                    if r.status_code == 200:
                        data = r.json()
                        models = data.get("data", []) or data.get("models", [])
                        for m in models:
                            mid = m.get("id") or m.get("name") or ""
                            st = (m.get("status") or m.get("state") or "").lower()
                            if mid == self.cfg.model and st in ("loaded", "ready", "running"):
                                _log.info("llamacpp model ready after poll: %s", self.cfg.model)
                                return True
            except Exception as e:
                _log.debug("llamacpp poll error (continuing): %s", e)
            await asyncio.sleep(interval)
        _log.warning("llamacpp model wait timeout (%.0fs): %s", timeout, self.cfg.model)
        return False

    # ------------------------------------------------------------------ #
    async def list_models(self) -> list[dict[str, Any]]:
        """Liste les modèles disponibles."""
        try:
            resp = await self._client.get("/models")
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("data", [])
        except Exception:
            return []
