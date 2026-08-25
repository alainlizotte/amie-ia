# Tests du module auth (comptes PBKDF2 + tokens HMAC + migration legacy).

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json  # noqa: E402

from server import auth as auth_mod  # noqa: E402
from server.config import get_config  # noqa: E402


def _data_dir() -> str:
    return str(get_config().abs(get_config().paths.data_dir))


class TestComptes:
    def test_creation_puis_verification(self):
        ok, msg = auth_mod.creer_utilisateur(_data_dir(), "Beatrice", "s3cret!")
        assert ok, msg
        assert auth_mod.verifier_identifiants(_data_dir(), "Beatrice", "s3cret!")
        assert not auth_mod.verifier_identifiants(_data_dir(), "Beatrice", "faux")
        # insensible à la casse
        assert auth_mod.verifier_identifiants(_data_dir(), " beatrice ", "s3cret!")

    def test_nom_trop_court_refuse(self):
        ok, _ = auth_mod.creer_utilisateur(_data_dir(), "ab", "motdepasse")
        assert not ok

    def test_mot_de_passe_trop_court_refuse(self):
        ok, _ = auth_mod.creer_utilisateur(_data_dir(), "Charlie", "abc")
        assert not ok

    def test_nom_deja_pris(self):
        auth_mod.creer_utilisateur(_data_dir(), "Dominique", "motdepasse")
        ok, msg = auth_mod.creer_utilisateur(_data_dir(), "dominique", "autre")
        assert not ok and "pris" in msg

    def test_hash_sale_pas_en_clair(self):
        auth_mod.creer_utilisateur(_data_dir(), "Eve", "motdepasse")
        with open(Path(_data_dir()) / "utilisateurs.json", encoding="utf-8") as f:
            data = json.load(f)
        entry = next(v for k, v in data.items() if k.lower() == "eve")
        assert "motdepasse" not in json.dumps(entry)
        assert entry["sel"] and entry["hash"]


class TestTokens:
    def test_token_valide(self):
        auth_mod.creer_utilisateur(_data_dir(), "Fabien", "motdepasse")
        token = auth_mod.generer_token(_data_dir(), "Fabien")
        nom = auth_mod.verifier_token(_data_dir(), token)
        assert nom == "Fabien"

    def test_token_falsifie_refuse(self):
        auth_mod.creer_utilisateur(_data_dir(), "Gaston", "motdepasse")
        token = auth_mod.generer_token(_data_dir(), "Gaston")
        faux = token[:-4] + ("0000" if token[-4:] != "0000" else "1111")
        assert auth_mod.verifier_token(_data_dir(), faux) is None

    def test_token_expirer_refuse(self):
        auth_mod.creer_utilisateur(_data_dir(), "Henri", "motdepasse")
        # Token fabriqué avec une expiration passée + mauvaise signature.
        assert auth_mod.verifier_token(_data_dir(), "Henri|1|abc") is None

    def test_utilisateur_depuis_header(self):
        auth_mod.creer_utilisateur(_data_dir(), "Isabelle", "motdepasse")
        token = auth_mod.generer_token(_data_dir(), "Isabelle")
        nom = auth_mod.utilisateur_depuis_header(
            _data_dir(), f"Bearer {token}"
        )
        assert nom == "Isabelle"
        assert auth_mod.utilisateur_depuis_header(_data_dir(), "") is None
        assert auth_mod.utilisateur_depuis_header(_data_dir(), "Bearer x") is None


class TestMigrationLegacy:
    def test_compte_sha256_migre_a_la_connexion(self):
        import hashlib

        data_dir = _data_dir()
        legacy_path = Path(data_dir) / "users.json"
        legacy_path.write_text(
            json.dumps({
                "users": {
                    "legacyleg": {
                        "nom": "legacyleg",
                        "password_sha256": hashlib.sha256(
                            "vieuxmdp".encode()
                        ).hexdigest(),
                        "created": "2026-01-01T00:00:00",
                    }
                }
            }),
            encoding="utf-8",
        )
        # Pas encore dans le nouveau fichier → vérification via legacy +
        # migration automatique en PBKDF2.
        assert auth_mod.verifier_identifiants(data_dir, "legacyleg", "vieuxmdp")
        # Maintenant migré : le nouveau fichier le contient.
        with open(Path(data_dir) / "utilisateurs.json", encoding="utf-8") as f:
            data = json.load(f)
        assert any(k.lower() == "legacyleg" for k in data)
        # Mauvais mot de passe refusé même en legacy.
        assert not auth_mod.verifier_identifiants(data_dir, "legacyleg", "faux")
        legacy_path.unlink()

    def test_connexion_generer_token_apres_migration(self):
        import hashlib

        data_dir = _data_dir()
        legacy_path = Path(data_dir) / "users.json"
        legacy_path.write_text(
            json.dumps({
                "users": {
                    "tokenleg": {
                        "nom": "tokenleg",
                        "password_sha256": hashlib.sha256(
                            "viemdp2".encode()
                        ).hexdigest(),
                    }
                }
            }),
            encoding="utf-8",
        )
        assert auth_mod.verifier_identifiants(data_dir, "tokenleg", "viemdp2")
        token = auth_mod.generer_token(data_dir, "tokenleg")
        assert auth_mod.verifier_token(data_dir, token) == "tokenleg"
        legacy_path.unlink()


class TestDureeToken:
    def test_duree_30_jours(self):
        assert auth_mod.TOKEN_DUREE_S == 30 * 24 * 3600
        # le token embarque une expiration future (~30 j).
        auth_mod.creer_utilisateur(_data_dir(), "Jules", "motdepasse")
        token = auth_mod.generer_token(_data_dir(), "Jules")
        exp = int(token.split("|")[1])
        assert exp > time.time() + 29 * 24 * 3600
