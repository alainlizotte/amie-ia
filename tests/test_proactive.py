# Tests des messages proactifs (silence 24 h → 1 message/jour, -50 pts si
# sans réponse avant le suivant, badge remis à zéro dès que l'utilisateur
# répond).

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.config import get_config  # noqa: E402
from server.main import (  # noqa: E402
    _proactive_due,
    _proactive_for_session,
    _state,
    app,
)
from tests.test_api import _auth, _inscription  # noqa: E402


def _data_dir():
    return get_config().abs(get_config().paths.data_dir)


def _set_profile(sid: str, **fields):
    st = _state(sid)
    profile = st.load()
    profile.update(fields)
    st.save(profile)


def _get_profile(sid: str):
    return _state(sid).load()


class _FakeChat:
    """Remplace app.state.client.chat/unload_model (aucun réseau)."""

    def __init__(self, content=None, raise_exc=None):
        self.content = content
        self.raise_exc = raise_exc
        self.calls = 0

    async def __call__(self, *a, **kw):
        self.calls += 1
        if self.raise_exc:
            raise self.raise_exc

        class R:
            pass

        r = R()
        r.content = self.content
        return r


async def _noop_unload(*a, **kw):
    return True


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.asyncio
async def test_message_proactif_apres_silence(client, monkeypatch):
    token = _inscription(client, "proactive1")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]

    # LLM injoignable → fallback déterministe ; pas d'appel réseau.
    fake = _FakeChat(raise_exc=RuntimeError("llm down"))
    monkeypatch.setattr(app.state.client, "chat", fake)
    monkeypatch.setattr(app.state.client, "unload_model", _noop_unload)

    # Silence de 25 h → message dû, sans pénalité (premier message).
    _set_profile(sid, last_interaction=(
        datetime.utcnow() - timedelta(hours=25)
    ).isoformat())
    await _proactive_for_session(sid)

    profile = _get_profile(sid)
    assert profile["unanswered_messages"] == 1
    assert profile["last_proactive_at"]
    assert profile["relationship_score"] == 100  # aucune pénalité
    # Message persisté dans l'historique chat.
    hist_path = Path(_data_dir()) / f"chat_{sid}.json"
    import json as _json
    hist = _json.loads(hist_path.read_text(encoding="utf-8"))
    assert hist and hist[-1]["role"] == "assistant" and hist[-1]["content"]

    # Badge visible dans le profil public (Mes rencontres).
    pub = client.get(f"/api/sessions/{sid}", headers=_auth(token)).json()
    assert pub["unanswered_messages"] == 1


@pytest.mark.asyncio
async def test_un_seul_message_par_jour(client, monkeypatch):
    token = _inscription(client, "proactive2")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]
    monkeypatch.setattr(app.state.client, "chat", _FakeChat(raise_exc=RuntimeError("x")))
    monkeypatch.setattr(app.state.client, "unload_model", _noop_unload)

    _set_profile(
        sid,
        last_interaction=(datetime.utcnow() - timedelta(hours=30)).isoformat(),
        last_proactive_at=(datetime.utcnow() - timedelta(hours=2)).isoformat(),
        unanswered_messages=1,
    )
    await _proactive_for_session(sid)

    # Interval 24 h non écoulé → pas de second message, pas de pénalité.
    profile = _get_profile(sid)
    assert profile["unanswered_messages"] == 1
    assert profile["relationship_score"] == 100


@pytest.mark.asyncio
async def test_penalite_50_sans_reponse(client, monkeypatch):
    token = _inscription(client, "proactive3")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]
    monkeypatch.setattr(app.state.client, "chat", _FakeChat(raise_exc=RuntimeError("x")))
    monkeypatch.setattr(app.state.client, "unload_model", _noop_unload)

    # 1er message non répondu il y a 25 h ; silence total de 49 h.
    _set_profile(
        sid,
        last_interaction=(datetime.utcnow() - timedelta(hours=49)).isoformat(),
        last_proactive_at=(datetime.utcnow() - timedelta(hours=25)).isoformat(),
        unanswered_messages=1,
    )
    await _proactive_for_session(sid)

    profile = _get_profile(sid)
    assert profile["unanswered_messages"] == 2
    assert profile["relationship_score"] == 100 - 50  # -50 points


@pytest.mark.asyncio
async def test_reponse_utilisateur_remet_compteur_a_zero(client, monkeypatch):
    token = _inscription(client, "proactive4")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]
    monkeypatch.setattr(app.state.client, "chat", _FakeChat(raise_exc=RuntimeError("x")))
    monkeypatch.setattr(app.state.client, "unload_model", _noop_unload)

    _set_profile(
        sid,
        last_interaction=(datetime.utcnow() - timedelta(hours=30)).isoformat(),
        last_proactive_at=(datetime.utcnow() - timedelta(hours=6)).isoformat(),
        unanswered_messages=2,
    )

    # L'utilisateur répond via le WS (LLM injoignable → tour en erreur mais
    # le reset doit être persisté AVANT la génération).
    with client.websocket_connect(f"/ws/{sid}") as ws:
        ws.send_json({"type": "join", "token": token})
        ws.receive_json()  # joined
        ws.send_json({"type": "say", "text": "salut, me revoilà !"})
        for _ in range(30):
            m = ws.receive_json()
            if m["type"] == "dm":
                break

    profile = _get_profile(sid)
    assert profile["unanswered_messages"] == 0

    # Et le message suivant du personnage (24 h plus tard) repart sans
    # pénalité.
    _set_profile(
        sid,
        last_interaction=(datetime.utcnow() - timedelta(hours=25)).isoformat(),
        last_proactive_at=(datetime.utcnow() - timedelta(hours=25)).isoformat(),
    )
    await _proactive_for_session(sid)
    profile = _get_profile(sid)
    assert profile["unanswered_messages"] == 1
    assert profile["relationship_score"] == 100


@pytest.mark.asyncio
async def test_aucun_message_au_stade_rejet(client):
    token = _inscription(client, "proactive5")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]
    _set_profile(
        sid,
        relationship_stage="rejet",
        relationship_score=50,
        last_interaction=(datetime.utcnow() - timedelta(hours=48)).isoformat(),
        last_proactive_at=(datetime.utcnow() - timedelta(hours=30)).isoformat(),
        unanswered_messages=1,
    )
    await _proactive_for_session(sid)
    profile = _get_profile(sid)
    assert profile["unanswered_messages"] == 1  # inchangé


@pytest.mark.asyncio
async def test_message_llm_lorsque_dispo(client, monkeypatch):
    token = _inscription(client, "proactive6")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]
    fake = _FakeChat(content="Hey ! Ça fait longtemps, quoi de neuf ? 😊")
    monkeypatch.setattr(app.state.client, "chat", fake)
    monkeypatch.setattr(app.state.client, "unload_model", _noop_unload)

    _set_profile(sid, last_interaction=(
        datetime.utcnow() - timedelta(hours=26)
    ).isoformat())
    await _proactive_for_session(sid)

    profile = _get_profile(sid)
    assert profile["unanswered_messages"] == 1
    import json as _json
    hist = _json.loads(
        (Path(_data_dir()) / f"chat_{sid}.json").read_text(encoding="utf-8")
    )
    assert hist[-1]["content"] == "Hey ! Ça fait longtemps, quoi de neuf ? 😊"
    assert fake.calls == 1


def test_proactive_due_pure():
    """Décision pure, sans serveur : fenêtres et pénalité."""
    from server.config import RelationConfig

    rcfg = RelationConfig()
    base = {
        "relationship_stage": "neutre",
        "last_interaction": (
            datetime.utcnow() - timedelta(hours=25)
        ).isoformat(),
    }
    assert _proactive_due(base, rcfg) == (True, False)

    # Pas encore 24 h de silence.
    soon = dict(base, last_interaction=datetime.utcnow().isoformat())
    assert _proactive_due(soon, rcfg) == (False, False)

    # Message récent → intervalle non écoulé.
    recent = dict(
        base,
        last_proactive_at=(datetime.utcnow() - timedelta(hours=2)).isoformat(),
    )
    assert _proactive_due(recent, rcfg) == (False, False)

    # Sans réponse → pénalité au message suivant.
    unanswered = dict(
        base,
        last_proactive_at=(datetime.utcnow() - timedelta(hours=25)).isoformat(),
        unanswered_messages=1,
    )
    assert _proactive_due(unanswered, rcfg) == (True, True)

    # Stade rejet → jamais.
    assert _proactive_due(dict(base, relationship_stage="rejet"), rcfg) == (False, False)


def test_fallback_gradation():
    """Le repli suit la gradation émotionnelle : ennui → inquiétude →
    tristesse → frustration → colère blessée (jamais de simple relance)."""
    from server.main import (
        PROACTIVE_ESCALATION,
        PROACTIVE_FALLBACKS,
        _fallback_proactive,
    )

    # Premier message : ouverture naturelle selon le stade.
    m0 = _fallback_proactive(
        {"relationship_stage": "neutre", "unanswered_messages": 0}
    )
    assert m0 in PROACTIVE_FALLBACKS["neutre"]

    # Chaque niveau de silence → le registre correspondant.
    for niveau, bank in enumerate(PROACTIVE_ESCALATION, start=1):
        m = _fallback_proactive(
            {"relationship_stage": "proche", "unanswered_messages": niveau}
        )
        assert m in bank

    # Au-delà du dernier niveau : on reste sur la colère blessée.
    m9 = _fallback_proactive(
        {"relationship_stage": "proche", "unanswered_messages": 9}
    )
    assert m9 in PROACTIVE_ESCALATION[-1]

    # Les registres changent bien entre les niveaux (gradation réelle).
    assert (
        PROACTIVE_ESCALATION[0][0] != PROACTIVE_ESCALATION[-1][0]
    )
