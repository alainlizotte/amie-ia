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
    ChatHistory,
    _clean_proactive_text,
    _cut_meta_block,
    _generate_proactive_message,
    _proactive_due,
    _proactive_for_session,
    _state,
    _too_similar,
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


def test_clean_proactive_text():
    """La sortie générée est assainie : pas de reprise du dernier message,
    pas de fuite d'analyse/instructions internes."""
    normal = "Hey ! Ça fait un bail, comment vas-tu ? 😊"
    assert _clean_proactive_text(normal) == normal

    prev = (
        "Ah, intéressant ! Les rencontres, c'est toujours une aventure, "
        "c'est vrai ? C'est vrai que ça permet d'apprendre des choses.\n\n"
        "Est-ce qu'il y a une rencontre qui t'a marqué récemment ?"
    )
    nouvelle = "C'est une bonne question… Et toi, tu as déjà eu un coup de cœur ?"

    # Reprise à l'identique du dernier message → retirée.
    assert _clean_proactive_text(prev + "\n\n" + nouvelle, prev) == nouvelle

    # Fuite d'analyse/instructions en fin de réponse → coupée.
    leaky = (
        nouvelle + "\n\n"
        "**Analyse de la situation:**\n"
        "1.  **Relation:** Froid (Score 129).\n"
        "2.  **Contexte:** Conversation sur les rencontres.\n"
        "3.  **Objectif:** Répondre à « Des nouvelles rencontres ».\n"
        "4.  **Règle Absolue:** Rester discrète."
    )
    assert _clean_proactive_text(leaky) == nouvelle

    # Le cas réellement rencontré : reprise du dernier message + analyse
    # fuitée → aucune de ces fuites ne doit atteindre l'utilisateur
    # (message vide → le repli déterministe prend le relais).
    assert _clean_proactive_text(
        prev + "\n\n**Analyse de la situation:**\n1. **Relation:** Froid (Score 129).",
        prev,
    ) == ""


@pytest.mark.asyncio
async def test_contexte_termine_par_cadrage(client, monkeypatch):
    """Le contexte LLM d'un message spontané se termine par un tour « user »
    de cadrage : l'écriture spontanée est la consigne COURANTE. Sans lui, le
    modèle répond à la vieille question de l'utilisateur restée en fin
    d'historique (cas observé en production)."""
    token = _inscription(client, "genhist1")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]

    hist = ChatHistory(sid)
    hist.append("user", "J'aime le mystère")
    hist.append("assistant", "Les mystères, c'est fascinant.")
    hist.append("user", "Des nouvelles rencontres")
    dernier_assistant = "Ah, intéressant ! Les rencontres, c'est toujours une aventure !"
    hist.append("assistant", dernier_assistant)

    captured = {}

    class _Recorder:
        async def chat(self, messages, temperature=None, max_tokens=None):
            captured["messages"] = list(messages)
            captured["max_tokens"] = max_tokens

            class R:
                pass

            r = R()
            r.content = "Hey… ça fait un moment. Tu es encore là ?"
            return r

    last = await _generate_proactive_message(
        _Recorder(), _get_profile(sid), sid,
        datetime.utcnow() - timedelta(hours=25), datetime.utcnow(),
    )

    msgs = captured["messages"]
    assert msgs[0].role == "system"
    # Le tour final est le cadrage — pas la vieille question, pas un assistant.
    assert msgs[-1].role == "user"
    assert "message spontané" in msgs[-1].content
    assert "heures ont passé" in msgs[-1].content
    assert msgs[-1].content != "Des nouvelles rencontres"
    # Génération bornée mais suffisante pour le raisonnement du modèle
    # (séparé du contenu visible) + le texto lui-même.
    assert captured["max_tokens"] is not None and captured["max_tokens"] >= 512
    assert last == "Hey… ça fait un moment. Tu es encore là ?"


# ---- Cas réels observés dans la session ef0547fb61 (Joannie) -------------- #
_DERNIER_JOANNIE = (
    "Ben, en ce moment, j'essaie d'écrire une nouvelle chanson, mais c'est "
    "une mélodie assez complexe. J'ai beaucoup de travail sur les paroles "
    "pour qu'elles transmettent vraiment une émotion forte, tu sais. "
    "C'est un gros défi, mais j'adore ça quand ça demande de la concentration."
)
_PARAPHRASE_JOANNIE = (
    "En fait, j'étais en train de travailler sur une nouvelle composition. "
    "C'est un vrai casse-tête créatif, mais j'adore l'aspect artistique "
    "quand ça demande de la concentration. 🎶"
)
_LEGITIME_JOANNIE = (
    "Hey ! Ça fait quelques jours… je me demandais ce que tu devenais. "
    "Tout va bien ?"
)


def test_too_similar_cas_reels():
    """La paraphrase observée en production est détectée ; un message
    spontané légitime (même sujet, autre propos) passe."""
    # Paraphrase du dernier message (cas réel du 28 août) → rehash.
    assert _too_similar(_PARAPHRASE_JOANNIE, _DERNIER_JOANNIE)
    # Copie exacte → rehash.
    assert _too_similar(_DERNIER_JOANNIE, _DERNIER_JOANNIE)
    # Nouveau propos → légitime.
    assert not _too_similar(_LEGITIME_JOANNIE, _DERNIER_JOANNIE)
    # Référence au sujet précédent sans reprendre les phrases → légitime.
    assert not _too_similar(
        "Alors, cette chanson, elle avance ? 🎶", _DERNIER_JOANNIE
    )


def test_coupe_fuite_current_state():
    """Fuite observée dans la session 28e5df15f2 : « [Current State: …] »,
    « [Goal: …] », « [Character: …] » — coupée comme les analyses."""
    texto = "On dirait que tu as disparu. Tout va bien de ton côté ?"
    leaky = (
        texto + "\n"
        "[Current State: Cold, 101/1000]\n"
        "[Goal: Send a spontaneous message, 1-3 short text phrases.]\n"
        "[Character: Elle, 28, Barista, Goth/Rebellious.]\n"
        "[Context: Late Wednesday evening, 23:46.]"
    )
    assert _cut_meta_block(leaky) == texto
    # Ligne « Goal: … » sans crochet → coupée aussi.
    assert _cut_meta_block(texto + "\nGoal: envoyer un message spontané.") == texto


class _SeqChat:
    """Fake séquentiel appelable : renvoie chaque contenu tour à tour."""

    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0

    async def __call__(self, messages, temperature=None, max_tokens=None):
        i = min(self.calls, len(self.contents) - 1)
        self.calls += 1

        class R:
            pass

        r = R()
        r.content = self.contents[i]
        return r


@pytest.mark.asyncio
async def test_paraphrase_persistante_bascule_sur_repli(client, monkeypatch):
    """Le LLM rehash le dernier message même après relance → le repli
    déterministe prend le relais (jamais d'écho dans l'historique)."""
    token = _inscription(client, "genpara1")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]

    hist = ChatHistory(sid)
    hist.append("user", "Sinon, tu travailles sur quel projet en ce moment ?")
    hist.append("assistant", _DERNIER_JOANNIE)

    fake = _SeqChat([_PARAPHRASE_JOANNIE, _PARAPHRASE_JOANNIE])
    monkeypatch.setattr(app.state.client, "chat", fake)
    monkeypatch.setattr(app.state.client, "unload_model", _noop_unload)

    _set_profile(sid, last_interaction=(
        datetime.utcnow() - timedelta(hours=26)
    ).isoformat())
    await _proactive_for_session(sid)

    assert fake.calls == 2  # relance effectuée avant d'abandonner
    hist2 = ChatHistory(sid).history
    assert hist2[-1].role == "assistant"
    # Le message envoyé n'est NI la paraphrase NI trop proche du dernier.
    assert hist2[-1].content != _PARAPHRASE_JOANNIE
    assert not _too_similar(hist2[-1].content, _DERNIER_JOANNIE)
    assert _get_profile(sid)["unanswered_messages"] == 1


@pytest.mark.asyncio
async def test_paraphrase_puis_reussite(client, monkeypatch):
    """1er essai = paraphrase, 2e essai = message correct → c'est le 2e qui
    est envoyé (la relance porte ses fruits, pas de repli inutile)."""
    token = _inscription(client, "genpara2")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]

    hist = ChatHistory(sid)
    hist.append("user", "Sinon, tu travailles sur quel projet en ce moment ?")
    hist.append("assistant", _DERNIER_JOANNIE)

    bon = "Hey ! Quelques jours sans nouvelles… je me demandais ce que tu devenais ?"
    fake = _SeqChat([_PARAPHRASE_JOANNIE, bon])
    monkeypatch.setattr(app.state.client, "chat", fake)
    monkeypatch.setattr(app.state.client, "unload_model", _noop_unload)

    _set_profile(sid, last_interaction=(
        datetime.utcnow() - timedelta(hours=26)
    ).isoformat())
    await _proactive_for_session(sid)

    assert fake.calls == 2
    hist2 = ChatHistory(sid).history
    assert hist2[-1].content == bon
    assert not _too_similar(hist2[-1].content, _DERNIER_JOANNIE)


@pytest.mark.asyncio
async def test_historique_purge_cicatrices(client):
    """Les cicatrices d'anciens proactifs défaillants (2 messages assistant
    consécutifs, le second copiant le premier) sont purgées au chargement —
    en mémoire seulement, le fichier reste intact."""
    token = _inscription(client, "scars1")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]

    import json as _json

    path = Path(_data_dir()) / f"chat_{sid}.json"
    dernier = "Bonne nuit à toi aussi. 😊 J'aimerais qu'on se reparle bientôt !"
    fuite = dernier + "\n[Current State: Cold, 101/1000]"
    path.write_text(
        _json.dumps([
            {"role": "user", "content": "Bonne nuit !"},
            {"role": "assistant", "content": dernier},
            {"role": "assistant", "content": fuite},      # écho + fuite
            {"role": "user", "content": "Me revoilà !"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )

    hist = ChatHistory(sid).history
    roles = [m.role for m in hist]
    assert roles == ["user", "assistant", "user"]
    assert hist[1].content == dernier
    # Le fichier n'a pas été réécrit.
    brut = _json.loads(path.read_text(encoding="utf-8"))
    assert len(brut) == 4


@pytest.mark.asyncio
async def test_append_refuse_doublon_assistant(client):
    """Garde-fou : un message assistant identique au précédent n'est jamais
    ajouté à l'historique (quelle que soit la source)."""
    token = _inscription(client, "dup1")["token"]
    sid = client.post(
        "/api/sessions", json={"preset_id": "clara_moreau"}, headers=_auth(token)
    ).json()["session_id"]

    hist = ChatHistory(sid)
    hist.append("user", "Salut !")
    hist.append("assistant", "Coucou, ça va ?")
    hist.append("assistant", "Coucou, ça va ?")  # écho → refusé
    hist.append("assistant", "Vraiment autre chose")  # différent → accepté

    contenu = [m.content for m in ChatHistory(sid).history]
    assert contenu.count("Coucou, ça va ?") == 1
    assert "Vraiment autre chose" in contenu
