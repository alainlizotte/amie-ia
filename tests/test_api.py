# Tests API REST + WebSocket via TestClient (backends externes désactivés).

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402


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


class TestLogin:
    def test_creation_premiere_connexion(self):
        with TestClient(app) as c:
            r = c.post("/api/login", json={"nom": "alice", "mot_de_passe": "abcd1234"})
            assert r.status_code == 200
            assert r.json()["nouveau"] is True

    def test_mauvais_mot_de_passe_401(self):
        with TestClient(app) as c:
            r = c.post("/api/login", json={"nom": "alice", "mot_de_passe": "faux"})
            assert r.status_code == 401

    def test_reconnexion_sans_creation(self):
        with TestClient(app) as c:
            r = c.post("/api/login", json={"nom": "alice", "mot_de_passe": "abcd1234"})
            assert r.json()["nouveau"] is False

    def test_champs_manquants_400(self):
        with TestClient(app) as c:
            assert c.post("/api/login", json={}).status_code == 400
            assert c.post("/api/login", json={"nom": "x", "mot_de_passe": "ab"}).status_code == 400


class TestPresets:
    def test_liste_personnages(self):
        with TestClient(app) as c:
            r = c.get("/api/presets")
            assert r.status_code == 200
            chars = r.json()["characters"]
            assert len(chars) >= 20
            assert {"id", "name", "gender"} <= set(chars[0].keys())


class TestSessions:
    def test_cycle_complet(self):
        with TestClient(app) as c:
            c.post("/api/login", json={"nom": "bob", "mot_de_passe": "abcd1234"})
            r = c.post(
                "/api/sessions",
                json={
                    "user": "bob",
                    "preset_id": "clara_moreau",
                    "user_info": {"name": "Alex"},
                },
            )
            assert r.status_code == 200
            sid = r.json()["session_id"]
            prof = r.json()["profile"]
            assert prof["character"]["name"] == "Clara Moreau" or prof["character"]["name"]
            assert prof["score"] == 100
            assert prof["stage"] == "froid"
            assert prof["portrait_url"] is None

            # Lecture par le propriétaire.
            assert c.get(f"/api/sessions/{sid}", params={"user": "bob"}).status_code == 200

            # Lecture par un autre utilisateur → 404 (pas 403).
            assert c.get(f"/api/sessions/{sid}", params={"user": "eve"}).status_code == 404

            # Liste : uniquement les siennes.
            lst = c.get("/api/sessions", params={"user": "bob"}).json()["sessions"]
            assert any(s["session_id"] == sid for s in lst)
            assert all(s["session_id"] != "" for s in lst)

            # Album vide mais présent.
            ph = c.get(f"/api/sessions/{sid}/photos", params={"user": "bob"})
            assert ph.status_code == 200 and ph.json()["photos"] == []

            # Suppression puis 404.
            assert c.delete(f"/api/sessions/{sid}", params={"user": "bob"}).status_code == 200
            assert c.get(f"/api/sessions/{sid}", params={"user": "bob"}).status_code == 404

    def test_session_custom_sans_preset(self):
        with TestClient(app) as c:
            c.post("/api/login", json={"nom": "carol", "mot_de_passe": "abcd1234"})
            r = c.post(
                "/api/sessions",
                json={
                    "user": "carol",
                    "character": {
                        "name": "Léo",
                        "age": "30",
                        "gender": "M",
                        "occupation": "cuisinier",
                    },
                },
            )
            assert r.status_code == 200
            prof = r.json()["profile"]
            assert prof["character"]["name"] == "Léo"
            assert prof["character"]["preset_id"] is None
            assert prof["events_total"] == 0  # pas de scénarios pour un custom

    def test_preset_inconnu_404(self):
        with TestClient(app) as c:
            c.post("/api/login", json={"nom": "dave", "mot_de_passe": "abcd1234"})
            r = c.post("/api/sessions", json={"user": "dave", "preset_id": "inconnu"})
            assert r.status_code == 404

    def test_user_requis(self):
        with TestClient(app) as c:
            assert c.post("/api/sessions", json={"preset_id": "clara_moreau"}).status_code == 400


class TestWebSocket:
    def _create(self, c, user="wsuser"):
        c.post("/api/login", json={"nom": user, "mot_de_passe": "abcd1234"})
        r = c.post(
            "/api/sessions",
            json={"user": user, "preset_id": "clara_moreau", "user_info": {"name": "Toto"}},
        )
        return r.json()["session_id"]

    def test_join_refuse_mauvais_mdp(self):
        with TestClient(app) as c:
            sid = self._create(c)
            with c.websocket_connect(f"/ws/{sid}") as ws:
                ws.send_json({"type": "join", "user": "wsuser", "password": "faux"})
                msg = ws.receive_json()
                assert msg["type"] == "sys" and msg["event"] == "auth_failed"

    def test_join_refuse_autre_utilisateur(self):
        with TestClient(app) as c:
            sid = self._create(c, "owner1")
            c.post("/api/login", json={"nom": "intrus", "mot_de_passe": "abcd1234"})
            with c.websocket_connect(f"/ws/{sid}") as ws:
                ws.send_json({"type": "join", "user": "intrus", "password": "abcd1234"})
                msg = ws.receive_json()
                assert msg["event"] == "auth_failed"

    def test_say_exige_join(self):
        with TestClient(app) as c:
            sid = self._create(c)
            with c.websocket_connect(f"/ws/{sid}") as ws:
                ws.send_json({"type": "say", "text": "coucou"})
                msg = ws.receive_json()
                assert msg["event"] == "auth_required"

    def test_join_puis_historique_et_echo(self):
        with TestClient(app) as c:
            sid = self._create(c)
            with c.websocket_connect(f"/ws/{sid}") as ws:
                ws.send_json({"type": "join", "user": "wsuser", "password": "abcd1234"})
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
                ws2_msgs = None
                with c.websocket_connect(f"/ws/{sid}") as ws2:
                    ws2.send_json({"type": "join", "user": "wsuser", "password": "abcd1234"})
                    j2 = ws2.receive_json()
                    ws2_msgs = j2["history"]
                assert any(h["role"] == "user" and "salut" in h["content"] for h in ws2_msgs)

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
