# Tests des options d'expérience (notifications OS, voix) et du profil vocal
# des personnages — server/main.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import load_config  # noqa: E402
from server.main import _options_utilisateur, _profil_voix  # noqa: E402
from server import user_profile as UP  # noqa: E402

_CFG = load_config()
_DATA = str(_CFG.abs(_CFG.paths.data_dir))


class TestOptionsExperience:
    def test_absent_signifie_active(self):
        profil = UP.sauver_profil(_DATA, "OptTest1", {"name": "Alex"})
        opts = _options_utilisateur(profil)
        assert opts["notifications"] is True
        assert opts["voix"] is True

    def test_desactivation_persiste(self):
        profil = UP.sauver_profil(_DATA, "OptTest2", {
            "notifications": False, "voix": False,
        })
        opts = _options_utilisateur(profil)
        assert opts["notifications"] is False
        assert opts["voix"] is False
        # Relecture depuis le disque : persisté.
        opts2 = _options_utilisateur(UP.charger_profil(_DATA, "opttest2"))
        assert opts2["notifications"] is False

    def test_valeurs_invalides_sont_actives(self):
        # Toute valeur autre que False explicite → activé (défaut sûr).
        profil = {"notifications": "bof", "voix": None}
        opts = _options_utilisateur(profil)
        assert opts["notifications"] is True and opts["voix"] is True


class TestGatingVoixParStade:
    """La voix n'est disponible qu'à partir du stade « chaleureux »."""

    def _profil_session(self, stage: str) -> dict:
        return {
            "meta": {"user": "VoixTest", "session_id": "abc123", "titre": "T"},
            "character": {
                "name": "Camille", "age": "27", "gender": "F",
                "personality": "Enthousiaste et solaire",
            },
            "relationship_score": 900,
            "relationship_stage": stage,
        }

    def test_voix_exposee_seulement_chaleureux_et_proche(self):
        from server.main import _public_profile
        from server.relation.state import RelationState

        st = RelationState(_DATA, "gatev")
        for stade in ("rejet", "froid", "reserve", "neutre"):
            pub = _public_profile(st, self._profil_session(stade))
            assert pub["voix"] is None, f"voix ne devrait pas exister à {stade}"
        for stade in ("chaleureux", "proche"):
            pub = _public_profile(st, self._profil_session(stade))
            assert pub["voix"] is not None, f"voix devrait exister à {stade}"
            assert pub["voix"]["genre"] == "femme"


class TestProfilVoix:
    def test_deterministe_par_genre(self):
        femme = _profil_voix({"gender": "F", "personality": ""})
        homme = _profil_voix({"gender": "M", "personality": ""})
        assert femme["genre"] == "femme" and homme["genre"] == "homme"
        # Défauts neutres.
        assert femme["pitch"] == 1.0 and femme["rate"] == 1.0

    def test_personnalite_energique_plus_rapide(self):
        v = _profil_voix({
            "gender": "F",
            "personality": "Enthousiaste, curieuse et solaire",
        })
        assert v["rate"] == 1.1

    def test_personnalite_calme_plus_lente(self):
        v = _profil_voix({
            "gender": "F",
            "personality": "Indépendante, réservée et posée",
        })
        assert v["rate"] == 0.9

    def test_personnalite_drole_pitch_basse(self):
        v = _profil_voix({
            "gender": "M",
            "personality": "Humour pince-sans-rire très développé",
        })
        assert v["pitch"] == 0.95

    def test_personnalite_douce_pitch_haute(self):
        v = _profil_voix({
            "gender": "F",
            "personality": "Empathique, bienveillante et tendre",
        })
        assert v["pitch"] == 1.05

    def test_insensible_aux_accents(self):
        v1 = _profil_voix({"gender": "F", "personality": "drole et taquin"})
        v2 = _profil_voix({"gender": "F", "personality": "drôle et taquin"})
        assert v1 == v2
