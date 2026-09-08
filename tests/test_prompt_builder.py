# Tests du prompt builder — le prompt système doit contenir tous les blocs.

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import load_config  # noqa: E402
from server.llm.prompt_builder import (  # noqa: E402
    JOURS_FR,
    MOIS_FR,
    PromptBuilder,
)


def _profile() -> dict:
    return {
        "meta": {"session_id": "s1", "user": "alain", "titre": "Rencontre"},
        "character": {
            "preset_id": None,
            "name": "Clara",
            "age": 28,
            "title": "Graphiste",
            "gender": "F",
            "occupation": "graphiste freelance",
            "interests": "cinéma, randonnée",
            "appearance": "brune, yeux verts",
            "personality": "réservée mais drôle",
            "parcours": {},
            "histoire_personnelle": "",
            "parcours_amoureux": "",
        },
        "user_info": {"name": "Alex", "preferences": "discussions calmes"},
        "relationship_score": 450,
        "relationship_stage": "neutre",
        "interaction_count": 12,
        "memories": [],
    }


def _event() -> dict:
    return {
        "event_id": "clara_moreau_C",
        "letter": "C",
        "title": "Une proposition inattendue",
        "tone": "success",
        "min_stage": "neutre",
        "body": "Clara propose d'aller voir une expo ensemble ce week-end.",
    }


class TestSystemMessage:
    def setup_method(self):
        self.pb = PromptBuilder(load_config())

    def test_contient_persona(self):
        msg = self.pb.build_system_message(_profile(), [], None)
        assert "Clara" in msg
        assert len(msg) > 200

    def test_contient_bloc_relation(self):
        msg = self.pb.build_system_message(_profile(), [], None)
        assert "Neutre" in msg          # libellé capitalisé (STAGE_LABELS)
        assert "450/1000" in msg

    def test_contient_souvenirs(self):
        msg = self.pb.build_system_message(
            _profile(), ["S'appelle Alex", "Aime la randonnée"], None
        )
        assert "S'appelle Alex" in msg
        assert "Aime la randonnée" in msg

    def test_contient_event_injecte(self):
        msg = self.pb.build_system_message(_profile(), [], _event())
        assert "expo" in msg

    def test_sans_event_nen_pas_parle(self):
        msg = self.pb.build_system_message(_profile(), [], None)
        assert "expo" not in msg

    def test_infos_utilisateur(self):
        msg = self.pb.build_system_message(_profile(), [], None)
        assert "Alex" in msg

    def test_contient_contexte_temporel(self):
        msg = self.pb.build_system_message(_profile(), [], None)
        assert "CONTEXTE TEMPOREL" in msg


class TestBlocTemps:
    def setup_method(self):
        self.pb = PromptBuilder(load_config())

    def test_date_complete(self):
        bloc = self.pb.build_time_block()
        now = datetime.now()
        assert MOIS_FR[now.month - 1] in bloc
        assert str(now.year) in bloc
        assert JOURS_FR[now.weekday()] in bloc

    def test_heure_presente(self):
        bloc = self.pb.build_time_block()
        assert re.search(r"il est \d{2}:\d{2}", bloc)

    def test_saison_presente(self):
        bloc = self.pb.build_time_block()
        assert any(s in bloc for s in ("printemps", "été", "automne", "hiver"))

    def test_moment_journee(self):
        bloc = self.pb.build_time_block()
        assert any(
            m in bloc
            for m in ("la nuit", "le matin", "l'après-midi", "la soirée")
        )

    def test_ne_pas_demander_lheure(self):
        bloc = self.pb.build_time_block()
        assert "demande JAMAIS" in bloc
