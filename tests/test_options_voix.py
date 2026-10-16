# Tests des options d'expérience (notifications OS, voix) et du profil vocal
# des personnages — server/main.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import load_config  # noqa: E402
from server import voice as VOIX  # noqa: E402
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


class TestGatingVocauxParStade:
    """Les vocaux n'existent qu'à partir du stade « chaleureux »,
    désactivables via le profil (server/voice.vocal_prevu)."""

    class _Cfg:
        enabled = True
        chance_per_reply = 1.0  # tirage toujours gagnant pour les tests
        max_chars = 450

    def test_gating_complet(self):
        profil = {
            "relationship_stage": "chaleureux",
            "character": {"gender": "F", "personality": "solaire"},
        }
        assert VOIX.vocal_prevu(profil, True, "chaleureux", self._Cfg()) is True
        # Option du profil désactivée → jamais.
        assert VOIX.vocal_prevu(profil, False, "chaleureux", self._Cfg()) is False
        # Stades bas → jamais.
        for st in ("rejet", "froid", "reserve", "neutre"):
            assert VOIX.vocal_prevu(
                {**profil, "relationship_stage": st}, True, st, self._Cfg()
            ) is False, f"pas de vocal à {st}"
        # Backend désactivé → jamais.
        assert VOIX.vocal_prevu(profil, True, "chaleureux", None) is False

    def test_proba_zero(self):
        class _Cfg0(self._Cfg):
            chance_per_reply = 0.0

        profil = {"relationship_stage": "proche"}
        assert VOIX.vocal_prevu(profil, True, "proche", _Cfg0()) is False

    def test_nettoyage_pour_synthese(self):
        brut = "Salut toi ! 😊 **regarde** ça : [un lien](https://x.y) `code` 🎉"
        net = VOIX.nettoyer_pour_voix(brut)
        assert "😊" not in net and "🎉" not in net
        assert "**" not in net and "`" not in net and "https" not in net
        assert "un lien" in net and "regarde" in net

    def test_troncature_sur_fin_de_phrase(self):
        long = ("Une phrase complète ici. " * 40).strip()
        net = VOIX.nettoyer_pour_voix(long, max_chars=200)
        assert len(net) <= 205
        assert net.endswith((".", "!", "?", "…", ","))


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
