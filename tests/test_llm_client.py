# Tests du client LLM : payload transmis à llama.cpp, notamment max_tokens.

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import LLMConfig  # noqa: E402
from server.llm.client import LLMClient, Message  # noqa: E402


def test_llm_config_max_tokens_default():
    assert LLMConfig().max_tokens == 8192


def test_chat_payload_contient_max_tokens(monkeypatch):
    cfg = LLMConfig(base_url="http://llamacpp:8080/v1", model="gemma", max_tokens=8192)
    client = LLMClient(cfg)
    sent_payload: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "salut"}, "finish_reason": "stop"}]}

    async def fake_post(url, json=None):
        sent_payload.update(json or {})
        return _Resp()

    async def noop():
        return True

    fake_client = type("FakeClient", (), {})()
    fake_client.post = fake_post
    monkeypatch.setattr(client, "ensure_model_loaded", noop)
    monkeypatch.setattr(client, "_client", fake_client)

    result = asyncio.run(client.chat([Message(role="user", content="allo")]))
    assert result.content == "salut"
    assert sent_payload["max_tokens"] == 8192
    assert sent_payload["stream"] is False