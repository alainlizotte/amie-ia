# Tests API REST + WebSocket via TestClient (backends externes désactivés).

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402


def _inscription(c: TestClient, nom: str, mdp: str = "abcd1234") -> dict:
    """Inscription ; si le compte existe déjà (test précédent), connexion."""
    r = c.post("/api/auth/inscription", json={"nom": nom, "mot_de_passe": mdp})
    if r.status_code == 400:
        r = c.post("/api/auth/connexion", json={"nom": nom, "mot_de_passe": mdp})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestHealth:
    def test_health_degrade_ok(self):
        with TestClient(app) as c:
            r = c.get("/api/health")
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            # Backends désactivés en test : dégradé mais fonctionnel.
            assert body["model_available"] is False
            assert body["memory_enabled"] is False


class TestAuth:
    def test_inscription_renvoie_token(self):
        with TestClient(app) as c:
            body = _inscription(c, "alice")
            assert body["token"] and body["utilisateur"] == "alice"

    def test_inscription_nom_pris_400(self):
        with TestClient(app) as c:
            _inscription(c, "alice2")
            r = c.post(
                "/api/auth/inscription",
                json={"nom": "ALICE2", "mot_de_passe": "abcd1234"},
            )
            assert r.status_code == 400

    def test_connexion_ok_et_mauvais_mdp_401(self):
        with TestClient(app) as c:
            _inscription(c, "aliced")
            ok = c.post(
                "/api/auth/connexion",
                json={"nom": "aliced", "mot_de_passe": "abcd1234"},
            )
            assert ok.status_code == 200 and ok.json()["token"]
            bad = c.post(
                "/api/auth/connexion",
                json={"nom": "aliced", "mot_de_passe": "faux"},
            )
            assert bad.status_code == 401

    def test_moi_sans_token_401(self):
        with TestClient(app) as c:
            assert c.get("/api/auth/moi").status_code == 401

    def test_moi_avec_token(self):
        with TestClient(app) as c:
            body = _inscription(c, "alicem")
            r = c.get("/api/auth/moi", headers=_auth(body["token"]))
            assert r.status_code == 200
            assert r.json()["utilisateur"] == "alicem"

    def test_token_invalide_401(self):
        with TestClient(app) as c:
            assert c.get(
                "/api/sessions", headers=_auth("faux|1|abc")
            ).status_code == 401


class TestPresets:
    def test_liste_personnages(self):
        with TestClient(app) as c:
            r = c.get("/api/presets")
            assert r.status_code == 200
            chars = r.json()["characters"]
            assert len(chars) >= 20
            assert {"id", "name", "gender"} <= set(chars[0].keys())


class TestSessions:
    def test_sessions_exigent_auth(self):
        with TestClient(app) as c:
            assert c.get("/api/sessions").status_code == 401
            assert c.post("/api/sessions", json={}).status_code == 401

    def test_cycle_complet(self):
        with TestClient(app) as c:
            body = _inscription(c, "bob")
            h = _auth(body["token"])
            r = c.post(
                "/api/sessions",
                json={
                    "preset_id": "clara_moreau",
                    "user_info": {"name": "Alex"},
                },
                headers=h,
            )
            assert r.status_code == 200
            sid = r.json()["session_id"]
            prof = r.json()["profile"]
            assert prof["character"]["name"]
            assert prof["score"] == 100
            assert prof["stage"] == "froid"
            assert prof["portrait_url"] is None
            assert prof["unanswered_messages"] == 0

            # Lecture par le propriétaire.
            assert c.get(f"/api/sessions/{sid}", headers=h).status_code == 200

            # Lecture par un autre utilisateur → 404 (pas 403).
            h2 = _auth(_inscription(c, "eve")["token"])
            assert c.get(f"/api/sessions/{sid}", headers=h2).status_code == 404

            # Liste : uniquement les siennes.
            lst = c.get("/api/sessions", headers=h).json()["sessions"]
            assert any(s["session_id"] == sid for s in lst)
            assert all(
                "unanswered_messages" in s and "last_message" in s for s in lst
            )

            # Album vide mais présent.
            ph = c.get(f"/api/sessions/{sid}/photos", headers=h)
            assert ph.status_code == 200 and ph.json()["photos"] == []

            # Suppression puis 404.
            assert c.delete(f"/api/sessions/{sid}", headers=h).status_code == 200
            assert c.get(f"/api/sessions/{sid}", headers=h).status_code == 404

    def test_session_custom_sans_preset(self):
        with TestClient(app) as c:
            h = _auth(_inscription(c, "carol")["token"])
            r = c.post(
                "/api/sessions",
                json={
                    "character": {
                        "name": "Léo",
                        "age": "30",
                        "gender": "M",
                        "occupation": "cuisinier",
                    },
                },
                headers=h,
            )
            assert r.status_code == 200
            prof = r.json()["profile"]
            assert prof["character"]["name"] == "Léo"
            assert prof["character"]["preset_id"] is None
            assert prof["events_total"] == 0  # pas de scénarios pour un custom

    def test_preset_inconnu_404(self):
        with TestClient(app) as c:
            h = _auth(_inscription(c, "dave")["token"])
            r = c.post(
                "/api/sessions", json={"preset_id": "inconnu"}, headers=h
            )
            assert r.status_code == 404


class TestWebSocket:
    def _create(self, c, user="wsuser"):
        body = _inscription(c, user)
        r = c.post(
            "/api/sessions",
            json={"preset_id": "clara_moreau", "user_info": {"name": "Toto"}},
            headers=_auth(body["token"]),
        )
        return r.json()["session_id"], body["token"]

    def test_join_refuse_mauvais_token(self):
        with TestClient(app) as c:
            sid, _ = self._create(c)
            with c.websocket_connect(f"/ws/{sid}") as ws:
                ws.send_json({"type": "join", "token": "faux|1|abc"})
                msg = ws.receive_json()
                assert msg["type"] == "sys" and msg["event"] == "auth_failed"

    def test_join_refuse_autre_utilisateur(self):
        with TestClient(app) as c:
            sid, _ = self._create(c, "owner1")
            token_intrus = _inscription(c, "intrus")["token"]
            with c.websocket_connect(f"/ws/{sid}") as ws:
                ws.send_json({"type": "join", "token": token_intrus})
                msg = ws.receive_json()
                assert msg["event"] == "auth_failed"

    def test_say_exige_join(self):
        with TestClient(app) as c:
            sid, _ = self._create(c)
            with c.websocket_connect(f"/ws/{sid}") as ws:
                ws.send_json({"type": "say", "text": "coucou"})
                msg = ws.receive_json()
                assert msg["event"] == "auth_required"

    def test_join_puis_historique_et_echo(self):
        with TestClient(app) as c:
            sid, token = self._create(c)
            with c.websocket_connect(f"/ws/{sid}") as ws:
                ws.send_json({"type": "join", "token": token})
                joined = ws.receive_json()
                assert joined["event"] == "joined"
                assert joined["history"] == []
                assert joined["profile"]["interaction_count"] == 0

                # Tour complet : LLM injoignable → dm d'erreur propre,
                # mais l'écho player et le typing doivent passer.
                ws.send_json({"type": "say", "text": "salut !"})
                seen = set()
                dm = None
                for _ in range(20):
                    m = ws.receive_json()
                    seen.add(m["type"])
                    if m["type"] == "dm":
                        dm = m
                        break
                assert "player" in seen and "typing" in seen and dm is not None

                # Le message utilisateur est persisté dans l'historique.
                with c.websocket_connect(f"/ws/{sid}") as ws2:
                    ws2.send_json({"type": "join", "token": token})
                    j2 = ws2.receive_json()
                    msgs = j2["history"]
                assert any(
                    h["role"] == "user" and "salut" in h["content"] for h in msgs
                )

    def test_session_inexistante_ferme(self):
        with TestClient(app) as c:
            with c.websocket_connect("/ws/nexistepas") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "sys" and msg["event"] == "error"


class TestStaticFallback:
    def test_racine_sans_build_404_json(self):
        # static/ existe (build effectif) → index.html servi ; sinon JSON 404.
        with TestClient(app) as c:
            r = c.get("/")
            assert r.status_code in (200, 404)

    def test_routes_reservees_non_servies_par_fallback(self):
        with TestClient(app) as c:
            r = c.get("/api/inexistant")
            assert r.status_code == 404
