# Tests du profil utilisateur « dating app » : module, API REST, injection
# dans le prompt et analyse vision (simulée).

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from server import user_profile as UP  # noqa: E402
from server.config import load_config  # noqa: E402
from server.llm.prompt_builder import PromptBuilder  # noqa: E402
from server.main import app  # noqa: E402

_CFG = load_config()
_DATA = str(_CFG.abs(_CFG.paths.data_dir))

# PNG 1×1 transparent (valide, même pas besoin de vision pour le stockage).
_PNG_1PX = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
    )
).decode("ascii")


def _data_url() -> str:
    return f"data:image/png;base64,{_PNG_1PX}"


# --------------------------------------------------------------------------- #
#  Module de stockage.
# --------------------------------------------------------------------------- #
class TestModule:
    def test_sauver_charger_champs_autorises(self):
        UP.sauver_profil(_DATA, "ProfTest", {
            "name": "Alex", "age": 32, "hack": "non", "photo_description": "desc",
        })
        p = UP.charger_profil(_DATA, "prof test")  # clé normalisée
        assert p["name"] == "Alex"
        assert p["age"] == 32
        assert "hack" not in p
        assert p["photo_description"] == "desc"  # champ technique autorisé

    def test_purger_analyse_photo(self):
        UP.sauver_profil(_DATA, "ProfTest", {"photo_description": "x", "photo_erreur": "y"})
        UP.purger_analyse_photo(_DATA, "prof test")
        p = UP.charger_profil(_DATA, "prof test")
        assert "photo_description" not in p and "photo_erreur" not in p

    def test_sauver_photo_et_chemin(self):
        dest, mime = UP.sauver_photo(_DATA, "ProfTest", _data_url())
        assert dest.is_file() and mime == "image/png"
        assert UP.photo_path(_DATA, "prof test") == dest

    def test_sauver_photo_format_invalide(self):
        try:
            UP.sauver_photo(_DATA, "ProfTest", "data:text/plain;base64,aGk=")
            assert False, "ValueError attendu"
        except ValueError:
            pass

    def test_photo_absente_none(self):
        assert UP.photo_path(_DATA, "jamais-uploadé-xyz") is None


# --------------------------------------------------------------------------- #
#  API REST.
# --------------------------------------------------------------------------- #
def _inscription(c: TestClient, nom: str, mdp: str = "abcd1234") -> dict:
    r = c.post("/api/auth/inscription", json={"nom": nom, "mot_de_passe": mdp})
    if r.status_code == 400:
        r = c.post("/api/auth/connexion", json={"nom": nom, "mot_de_passe": mdp})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestApiMonProfil:
    def test_get_vide_puis_put_et_get(self):
        with TestClient(app) as c:
            tok = _inscription(c, "profalice")["token"]
            r = c.get("/api/mon-profil", headers=_auth(tok))
            assert r.status_code == 200
            assert r.json()["profil"]["name"] == ""

            r = c.put(
                "/api/mon-profil",
                json={"name": "Alice", "age": 29, "interests": "escalade", "hack": "x"},
                headers=_auth(tok),
            )
            assert r.status_code == 200
            p = r.json()["profil"]
            assert p["name"] == "Alice" and p["age"] == 29 and p["interests"] == "escalade"
            assert "hack" not in p

            r = c.get("/api/mon-profil", headers=_auth(tok))
            assert r.json()["profil"]["name"] == "Alice"

    def test_put_sans_auth_401(self):
        with TestClient(app) as c:
            assert c.put("/api/mon-profil", json={"name": "X"}).status_code == 401

    def test_upload_photo_renvoie_url(self):
        with TestClient(app) as c:
            tok = _inscription(c, "profbob")["token"]
            r = c.post(
                "/api/mon-profil/photo",
                json={"data": _data_url()},
                headers=_auth(tok),
            )
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            # LLM de test configuré (injoignable) → la tâche d'analyse est
            # lancée et échouera silencieusement (photo_erreur renseignée).
            assert isinstance(body["analyse_en_cours"], bool)
            # La photo est désormais accessible (auth).
            r2 = c.get("/api/mon-profil/photo", headers=_auth(tok))
            assert r2.status_code == 200 and r2.headers["content-type"] == "image/png"
            # Et le GET profil expose l'URL.
            r3 = c.get("/api/mon-profil", headers=_auth(tok))
            assert r3.json()["photo_url"] == "/api/mon-profil/photo"

    def test_upload_photo_invalide_400(self):
        with TestClient(app) as c:
            tok = _inscription(c, "profcarl")["token"]
            r = c.post(
                "/api/mon-profil/photo",
                json={"data": "boop"},
                headers=_auth(tok),
            )
            assert r.status_code == 400

    def test_profils_isoles_par_compte(self):
        with TestClient(app) as c:
            t1 = _inscription(c, "profisol1")["token"]
            t2 = _inscription(c, "profisol2")["token"]
            c.put("/api/mon-profil", json={"name": "Un"}, headers=_auth(t1))
            c.put("/api/mon-profil", json={"name": "Deux"}, headers=_auth(t2))
            assert c.get("/api/mon-profil", headers=_auth(t1)).json()["profil"]["name"] == "Un"
            assert c.get("/api/mon-profil", headers=_auth(t2)).json()["profil"]["name"] == "Deux"


# --------------------------------------------------------------------------- #
#  Injection dans le prompt système.
# --------------------------------------------------------------------------- #
class TestPromptUserCard:
    def _pb(self) -> PromptBuilder:
        return PromptBuilder(_CFG)

    def _profile(self) -> dict:
        return {
            "meta": {"session_id": "s1", "user": "u", "titre": "R"},
            "character": {"name": "Clara", "age": 28, "gender": "F"},
            "user_info": {},
            "relationship_score": 450,
            "relationship_stage": "neutre",
        }

    def test_fiche_complete_injectee(self):
        up = {
            "name": "Alex", "age": 32, "gender": "H",
            "occupation": "tech en informatique", "interests": "cuisine, vélo",
            "personality": "curieux", "histoire": "né à Québec",
            "parcours_amoureux": "célibataire", "preferences": "discussions sincères",
            "photo_description": "Grand, cheveux bruns, t-shirt noir.",
        }
        msg = self._pb().build_system_message(self._profile(), [], None, user_profil=up)
        assert "Alex" in msg and "32" in msg
        assert "tech en informatique" in msg
        assert "Grand, cheveux bruns" in msg
        assert "d'après sa photo de profil" in msg
        assert "discussions sincères" in msg

    def test_categories_vides_omises(self):
        msg = self._pb().build_system_message(self._profile(), [], None, user_profil={"name": "Alex"})
        assert "Alex" in msg
        assert "Métier" not in msg and "Situation amoureuse" not in msg

    def test_sans_profil_retombe_sur_user_info_session(self):
        prof = self._profile()
        prof["user_info"] = {"name": "Sam", "preferences": "calme"}
        msg = self._pb().build_system_message(prof, [], None)
        assert "Sam" in msg and "calme" in msg
