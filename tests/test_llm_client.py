# Tests du client LLM : payload transmis à llama.cpp, notamment max_tokens,
# normalisation des messages (templates strictes Qwen 3.5) et strip thinking.

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import LLMConfig  # noqa: E402
from server.llm.client import (  # noqa: E402
    LLMClient,
    Message,
    _normaliser_messages,
    _strip_thinking,
)


def test_llm_config_max_tokens_default():
    assert LLMConfig().max_tokens == 8192


def test_normaliser_messages_system_hors_tete_devenu_user():
    """Template Qwen 3.5 stricte : system uniquement à l'index 0."""
    msgs = [
        Message(role="user", content="salut"),
        Message(role="assistant", content="coucou"),
        Message(role="system", content="reste dans ton rôle"),
        Message(role="user", content="encore moi"),
    ]
    out = _normaliser_messages(msgs)
    assert all(m.role != "system" for m in out)
    assert out[0].role == "user" and out[0].content == "salut"
    assert out[2].role == "user"
    assert "reste dans ton rôle" in out[2].content


def test_normaliser_messages_system_en_tete_inchange():
    msgs = [
        Message(role="system", content="tu es Joannie"),
        Message(role="user", content="salut"),
    ]
    out = _normaliser_messages(msgs)
    assert out[0].role == "system" and out[0].content == "tu es Joannie"
    assert out[1].role == "user"


def test_strip_thinking_qwen():
    text = "<think>raisonnement interne</think>Salut toi !"
    assert _strip_thinking(text) == "Salut toi !"


def test_strip_thinking_qwen_non_ferme():
    text = "<think>raisonnement coupé en fin de génération"
    assert _strip_thinking(text) == ""


def test_strip_thinking_gemma():
    text = "<|channel>thought|hmm<channel|>Bonjour !"
    assert _strip_thinking(text) == "Bonjour !"


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


def test_chat_payload_desactive_thinking_qwen(monkeypatch):
    """think: false → chat_template_kwargs {enable_thinking: false} (Qwen 3.5)."""
    cfg = LLMConfig(base_url="http://llamacpp:8080/v1", model="qwen", think=False)
    client = LLMClient(cfg)
    sent_payload: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    async def fake_post(url, json=None):
        sent_payload.update(json or {})
        return _Resp()

    async def noop():
        return True

    fake_client = type("FakeClient", (), {})()
    fake_client.post = fake_post
    monkeypatch.setattr(client, "ensure_model_loaded", noop)
    monkeypatch.setattr(client, "_client", fake_client)

    asyncio.run(client.chat([Message(role="user", content="allo")]))
    assert sent_payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_chat_payload_thinking_actif_sans_kwargs(monkeypatch):
    """think: true → aucun chat_template_kwargs injecté."""
    cfg = LLMConfig(base_url="http://llamacpp:8080/v1", model="qwen", think=True)
    client = LLMClient(cfg)
    sent_payload: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    async def fake_post(url, json=None):
        sent_payload.update(json or {})
        return _Resp()

    async def noop():
        return True

    fake_client = type("FakeClient", (), {})()
    fake_client.post = fake_post
    monkeypatch.setattr(client, "ensure_model_loaded", noop)
    monkeypatch.setattr(client, "_client", fake_client)

    asyncio.run(client.chat([Message(role="user", content="allo")]))
    assert "chat_template_kwargs" not in sent_payload


def test_chat_normalise_system_hors_tete_avant_envoi(monkeypatch):
    """Les messages system hors index 0 partent en role=user (template Qwen)."""
    cfg = LLMConfig(base_url="http://llamacpp:8080/v1", model="qwen")
    client = LLMClient(cfg)
    sent_payload: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    async def fake_post(url, json=None):
        sent_payload.update(json or {})
        return _Resp()

    async def noop():
        return True

    fake_client = type("FakeClient", (), {})()
    fake_client.post = fake_post
    monkeypatch.setattr(client, "ensure_model_loaded", noop)
    monkeypatch.setattr(client, "_client", fake_client)

    msgs = [
        Message(role="system", content="persona"),
        Message(role="user", content="salut"),
        Message(role="system", content="rappel : reste en personnage"),
    ]
    asyncio.run(client.chat(msgs))
    roles = [m["role"] for m in sent_payload["messages"]]
    assert roles == ["system", "user", "user"]