# Tests du scoring déterministe — inclut la régression du bug « con/content ».

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.relation.scoring import (  # noqa: E402
    apply_time_decay,
    compute_delta,
)


class TestRegressionWordBoundaries:
    """Bug historique : « con » matchait « content » → -4 injustifié."""

    def test_accueil_amical_ne_sanctionne_pas(self):
        delta = compute_delta(
            "Salut Clara ! Content de te parler enfin. Moi c'est Alex, ça va ?",
            "...",
            "froid",
        )
        assert delta >= 1  # politesse seule

    def test_menu_ne_declenche_pas_nu(self):
        assert compute_delta("quel menu recommandes-tu ?", "...", "reserve") >= 0

    def test_annuaire_ne_declenche_pas_nul(self):
        # Aucun mot-clé neutre ni négatif dans cette phrase.
        assert compute_delta("je cherche dans l'annuaire", "...", "neutre") == 0


class TestInsultes:
    def test_insulte_dirigee_malus_fort(self):
        d = compute_delta("tu es vraiment conne et stupide", "...", "chaleureux")
        assert d <= -8

    def test_insulte_non_dirigee(self):
        d = compute_delta("cette merde ne marche pas, dégage", "...", "proche")
        assert d <= -5

    def test_mot_inoffensif_contenant_con(self):
        # « contenu », « commentaire » ne doivent rien coûter.
        assert compute_delta("ton commentaire a du contenu intéressant", "...", "neutre") >= 0


class TestPositifs:
    def test_compliment_tu_es_adjectif(self):
        assert compute_delta("Tu es vraiment passionnante", "...", "froid") >= 3

    def test_mots_positifs_cumules_plafonnes(self):
        d = compute_delta(
            "merci super génial magnifique bravo excellent parfait adorable",
            "...", "froid",
        )
        assert d == 8  # clamp delta_max

    def test_excuses(self):
        assert compute_delta("pardon, je n'aurais pas dû dire ça", "...", "rejet") >= 2

    def test_engagement_message_long(self):
        long_msg = "j'aime bien discuter avec toi " * 10  # > 200 chars
        assert compute_delta(long_msg, "...", "neutre") >= 2


class TestInsistance:
    def test_refusee_aux_stades_bas(self):
        for st in ("rejet", "froid", "reserve", "neutre"):
            assert compute_delta("envoie une photo de toi", "...", st) <= -3

    def test_toleree_au_stade_proche_pas_de_malus_specifique(self):
        # Au stade proche, pas de malus d'insistance (peut rester neutre).
        assert compute_delta("envoie une photo de toi", "...", "proche") == 0


class TestClamp:
    def test_plancher(self):
        horrible = "tu es une stupide connasse débile idiote, je te déteste"
        assert compute_delta(horrible, "...", "rejet") == -10


class TestTimeDecay:
    NOW = datetime(2026, 8, 21, 12, 0, 0)

    def test_pas_de_decay_sans_derniere_interaction(self):
        score, applied = apply_time_decay(500, None, self.NOW)
        assert score == 500 and not applied

    def test_grace_periode(self):
        last = datetime(2026, 8, 19, 12, 0, 0).isoformat()  # 2 jours avant
        score, applied = apply_time_decay(500, last, self.NOW, days_grace=3)
        assert score == 500 and not applied

    def test_decay_lineaire(self):
        last = datetime(2026, 8, 8, 12, 0, 0).isoformat()  # 13 jours : 10 j comptés
        score, applied = apply_time_decay(
            500, last, self.NOW, days_grace=3, points_per_day=10, max_loss=150
        )
        assert applied and score == 400

    def test_decay_plafonne(self):
        last = datetime(2026, 1, 1, 12, 0, 0).isoformat()  # très ancien
        score, _ = apply_time_decay(500, last, self.NOW, max_loss=150)
        assert score == 350

    def test_jamais_sous_zero(self):
        last = datetime(2026, 1, 1, 12, 0, 0).isoformat()
        score, _ = apply_time_decay(100, last, self.NOW, max_loss=150)
        assert score == 0

    def test_date_invalide_ignoree(self):
        score, applied = apply_time_decay(500, "pas-une-date", self.NOW)
        assert score == 500 and not applied
