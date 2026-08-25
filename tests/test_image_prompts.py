# Tests des prompts photo — scène dérivée de la conversation, cadrage
# selfie par défaut, garde-fous de tenue.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.image.helpers import (  # noqa: E402
    director_system,
    photo_prompt_for_stage,
    sanitize_scene,
    selfie_clause,
)

_CHAR = {
    "name": "Clara",
    "age": "23",
    "gender": "F",
    "appearance": "tall brunette",
    "interests": "vintage shopping",
}


class TestSelfie:
    def test_cadrage_selfie_par_defaut(self):
        p = photo_prompt_for_stage(_CHAR, "neutre")
        assert "selfie" in p
        assert "phone held in her own hand" in p
        assert "arm's length" in p

    def test_selfie_clause_masculine(self):
        c = dict(_CHAR, gender="M")
        s = selfie_clause(c)
        assert "himself" in s
        assert "his own hand" in s

    def test_scene_sans_cadrage_selfie_ajoute(self):
        p = photo_prompt_for_stage(
            _CHAR, "neutre", scene="sitting at the dinner table, candlelight",
        )
        assert "sitting at the dinner table" in p
        assert "selfie" in p  # selfie par défaut même avec scène

    def test_avis_contraire_dans_la_scene_selfie_retire(self):
        # La scène réclame explicitement un autre cadrage → pas de selfie.
        p = photo_prompt_for_stage(
            _CHAR, "neutre",
            scene="sitting at the piano, photo taken by her sister",
        )
        assert "selfie" not in p
        assert "taken by her sister" in p

    def test_avis_contraire_dans_le_hint_selfie_retire(self):
        p = photo_prompt_for_stage(
            _CHAR, "neutre",
            user_hint="photo en miroir dans le salon",
            scene="standing in the living room",
        )
        assert "selfie" not in p
        assert "standing in the living room" in p

    def test_hint_selfie_explicite_pas_de_doublon(self):
        # Si la scène dit déjà « selfie », la clause n'est pas réinjectée.
        p = photo_prompt_for_stage(
            _CHAR, "neutre", scene="gym selfie after workout, smiling",
        )
        assert p.count("selfie") == 1


class TestScene:
    def test_scene_presente_fiche_non_reinjectee(self):
        # Avec une scène, la fiche (style quotidien, intérêts) ne doit PAS
        # coexister avec elle : source de directives contradictoires.
        p = photo_prompt_for_stage(
            _CHAR, "neutre", user_hint="au café",
            scene="sitting at the dinner table, wearing a red dress",
        )
        assert "tall brunette" not in p          # apparence de la fiche
        assert "vintage shopping" not in p       # intérêts de la fiche
        assert "au café" not in p                # hint déjà passé au directeur
        assert "wearing a red dress" in p        # la scène fait foi


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
        assert "maximum 60 words" in c

    def test_consigne_proche_libere(self):
        assert "no clothing restriction" in director_system(_CHAR, "proche")

    def test_consigne_utilise_le_pronom(self):
        assert "her pose" in director_system(_CHAR, "neutre")

    def test_consigne_selfie_par_defaut(self):
        c = director_system(_CHAR, "neutre")
        assert "DEFAULT CAMERA FRAMING" in c
        assert "selfie" in c.lower()

    def test_fiche_apparence_transmise_au_directeur(self):
        # Le directeur reçoit l'apparence fixe : il décrit l'ensemble,
        # la fiche n'est plus réinjectée dans le prompt final.
        assert "tall brunette" in director_system(_CHAR, "neutre")

    def test_tenue_actuelle_peut_différer_du_style_quotidien(self):
        c = director_system(_CHAR, "proche")
        assert "may differ from her usual everyday style" in c

    def test_demande_acceptee_prioritaire(self):
        c = director_system(_CHAR, "neutre",
                            user_request="sitting at the table facing me")
        assert "TOP PRIORITY" in c
        assert "sitting at the table facing me" in c

    def test_sans_demande_pas_de_section_instruction(self):
        assert "explicitly asks" not in director_system(_CHAR, "neutre")
