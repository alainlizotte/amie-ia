# Tests des prompts photo — scène dérivée de la conversation, POV, garde-fous.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.image.helpers import (  # noqa: E402
    director_system,
    photo_prompt_for_stage,
    pov_clause,
    sanitize_scene,
)

_CHAR = {
    "name": "Clara",
    "age": "23",
    "gender": "F",
    "appearance": "tall brunette",
    "interests": "vintage shopping",
}


class TestPov:
    def test_pov_toujours_present(self):
        p = photo_prompt_for_stage(_CHAR, "neutre")
        assert "point of view" in p
        assert "looks directly at you" in p

    def test_pov_clause_masculin(self):
        c = dict(_CHAR, gender="M")
        assert "he looks directly at you" in pov_clause(c)

    def test_scene_inserree_dans_le_prompt(self):
        p = photo_prompt_for_stage(
            _CHAR, "neutre", scene="sitting at the dinner table, candlelight",
        )
        assert "sitting at the dinner table" in p


class TestGardeFousTenue:
    def test_nudite_retiree_hors_proche(self):
        for stade in ("reserve", "neutre", "chaleureux"):
            s = sanitize_scene("lying nude on the bed, smiling", stade)
            assert "nude" not in s.lower()
            assert "lying on the bed" in s

    def test_nudite_autorisee_proche(self):
        s = sanitize_scene("lying nude on the bed", "proche")
        assert "nude" in s.lower()

    def test_tenue_contrainte_meme_avec_scene(self):
        # Même si la scène évoque un cadre intime, la clause de tenue reste.
        p = photo_prompt_for_stage(_CHAR, "neutre", scene="on the bed, evening")
        assert "fully dressed" in p

    def test_chaleureux_jamais_nu(self):
        p = photo_prompt_for_stage(_CHAR, "chaleureux")
        assert "never nude" in p

    def test_proche_sans_restriction(self):
        p = photo_prompt_for_stage(_CHAR, "proche")
        assert "unrestricted" in p


class TestSanitizeScene:
    def test_nettoie_guillemets_et_lignes(self):
        s = sanitize_scene('"at the kitchen,\ncooking pasta"', "neutre")
        assert '"' not in s and "\n" not in s
        assert "kitchen" in s and "cooking pasta" in s

    def test_vide_si_entree_vide(self):
        assert sanitize_scene("", "proche") == ""
        assert sanitize_scene(None, "proche") == ""

    def test_tronque_a_300(self):
        s = sanitize_scene("a" * 500, "proche")
        assert len(s) <= 300


class TestDirecteurPhoto:
    def test_consigne_contient_regle_tenue_neutre(self):
        c = director_system(_CHAR, "neutre")
        assert "fully dressed" in c
        assert "maximum 30 words" in c

    def test_consigne_proche_libere(self):
        assert "no clothing restriction" in director_system(_CHAR, "proche")

    def test_consigne_utilise_le_pronom(self):
        assert "her pose" in director_system(_CHAR, "neutre")

    def test_demande_acceptee_prioritaire(self):
        c = director_system(_CHAR, "neutre",
                            user_request="sitting at the table facing me")
        assert "TOP PRIORITY" in c
        assert "sitting at the table facing me" in c

    def test_sans_demande_pas_de_section_instruction(self):
        assert "explicitly asks" not in director_system(_CHAR, "neutre")
