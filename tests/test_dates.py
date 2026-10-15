# Tests des scénarios interactifs (« rendez-vous ») — dates.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.relation import dates as D  # noqa: E402
from server.relation.stages import STAGE_ORDER  # noqa: E402


def _profil(stage="neutre", score=500, interactions=10, character=None):
    return {
        "meta": {"user": "test", "session_id": "abc123"},
        "character": character or {
            "name": "Camille",
            "age": "27",
            "gender": "F",
            "interests": "L'escalade de bloc et la lecture",
        },
        "relationship_score": score,
        "relationship_stage": stage,
        "interaction_count": interactions,
        "dates_historique": [],
        "last_date_at": None,
        "date": None,
    }


def _force_date(profil, scenario_id="rdv_cafe"):
    """Place un scénario précis en état « proposition envoyée »."""
    scenario = next(s for s in D.BANQUE_DATES if s["id"] == scenario_id)
    D.demarrer_date(scenario, profil)
    return scenario


class TestDisponibilite:
    def test_aucune_proposition_au_rejet(self):
        assert D.date_dispo(_profil(stage="rejet"), "rejet") is None

    def test_minimum_interactions(self):
        assert D.date_dispo(_profil(interactions=2), "neutre") is None
        assert D.date_dispo(_profil(interactions=3), "neutre") is not None

    def test_cooldown_48h(self):
        from datetime import datetime, timedelta
        profil = _profil()
        profil["last_date_at"] = (
            datetime.utcnow() - timedelta(hours=2)
        ).isoformat()
        assert D.date_dispo(profil, "neutre") is None
        profil["last_date_at"] = (
            datetime.utcnow() - timedelta(hours=49)
        ).isoformat()
        assert D.date_dispo(profil, "neutre") is not None

    def test_gate_par_stade(self):
        """Aucun rendez-vous avant « neutre » ; à froid/réservé : None."""
        assert D.date_dispo(_profil(stage="froid"), "froid") is None
        assert D.date_dispo(_profil(stage="reserve"), "reserve") is None
        # À neutre : scénarios neutre-gated uniquement (aucun moment physique
        # anticipé — les sorties réelles attendent leur stade).
        for _ in range(30):
            scen = D.date_dispo(_profil(stage="neutre"), "neutre")
            assert scen is not None
            assert scen["min_stage"] == "neutre"
        # À proche : tout est éligible, avec variété réelle.
        ids = {D.date_dispo(_profil(stage="proche"), "proche")["id"]
               for _ in range(60)}
        assert len(ids) >= 3

    def test_modes_scenes(self):
        """Scénarios à distance vs présentiel explicites (crédibilité)."""
        distance = {"film_sync", "playlist", "cuisine_sync", "balade_commentee"}
        for scen in D.BANQUE_DATES:
            if scen["id"] in distance:
                assert scen["mode"] == "distance"
                assert scen.get("photo") is None  # pas de photo à distance
            else:
                assert scen["mode"] == "presentiel"

    def test_stades_couverts(self):
        """Un scénario est disponible à CHAQUE stade jouable (neutre → proche)
        et AUCUN avant « neutre »."""
        for st in STAGE_ORDER:
            profil = _profil(stage=st)
            profil["last_date_at"] = None
            scen = D.date_dispo(profil, st)
            if st in ("rejet", "froid", "reserve"):
                assert scen is None, f"aucun rendez-vous ne devrait exister à {st}"
            else:
                assert scen is not None, f"aucun scénario au stade {st}"

    def test_pas_de_proposition_si_date_en_cours(self):
        profil = _profil()
        _force_date(profil)
        assert D.date_dispo(profil, "neutre") is None


class TestPropositionEtReponses:
    def test_acceptation_ouvre_le_premier_beat(self):
        profil = _profil()
        scenario = _force_date(profil)
        res = D.traiter_tour_date(profil, "avec plaisir, j'ai hâte !")
        assert res is not None
        assert res["points"] == D.POINTS_ACCEPTATION
        assert res["mode"] == "ajoute" and res["fin"] is False
        assert profil["date"]["etat"] == "en_cours"
        assert profil["date"]["etape"] == 1
        assert "SCÈNE" in res["directive"]
        # Le premier beat est bien livré (contenu interpolé du scénario).
        assert scenario["beats"][0]["scene"][:40].split(",")[0].lower() in (
            res["directive"].lower()
        )

    def test_refus_clot_avec_dignite(self):
        profil = _profil()
        _force_date(profil)
        res = D.traiter_tour_date(profil, "désolé, pas possible cette semaine")
        assert res is not None
        assert res["fin"] is True and res["points"] == 0
        assert profil["date"] is None
        assert "DÉCLINÉ" in res["directive"]

    def test_evasif_une_relance_puis_abandon(self):
        profil = _profil()
        _force_date(profil)
        res1 = D.traiter_tour_date(profil, "bof, on verra")
        assert res1 is not None and res1["fin"] is False
        assert "SANS RÉPONSE CLAIRE" in res1["directive"]
        res2 = D.traiter_tour_date(profil, "je ne sais pas trop")
        assert res2 is not None and res2["fin"] is True
        assert "SANS SUITE" in res2["directive"]
        assert profil["date"] is None

    def test_proposal_interpole_les_interets(self):
        profil = _profil()
        scenario = next(
            s for s in D.BANQUE_DATES if "{interest1}" in s.get("proposal", "")
        )
        directive = D.directive_proposition(
            scenario, profil["character"], profil["relationship_stage"]
        )
        assert "escalade de bloc" in directive
        # L'acceptation livre le premier beat, pas la proposition.
        D.demarrer_date(scenario, profil)
        res = D.traiter_tour_date(profil, "bonne idée, hâte !")
        assert res["points"] == D.POINTS_ACCEPTATION


class TestBeatsEtMoments:
    def test_deroulement_complet_rdv_cafe(self):
        """Proposition → acceptation → beats → moment clé → photo → fin."""
        profil = _profil(stage="neutre")
        scenario = _force_date(profil, "rdv_cafe")

        # Acceptation → beat 0 (arrivée).
        res = D.traiter_tour_date(profil, "avec plaisir !")
        assert res["photo"] is None

        # Beat 1 (moment clé : terrasse / intérieur).
        res = D.traiter_tour_date(profil, "super !")
        assert "TERRASSE" in res["directive"] or "comptoir" in res["directive"].lower()

        # Moment clé résolu : la scène dédiée est livrée.
        res = D.traiter_tour_date(profil, "plutôt la terrasse au soleil !")
        assert res["fin"] is False
        assert res["photo"] is None
        assert profil["date"]["moment_resolu"] is True

        # La scène du moment livrée, on reprend : beat 2 (photo souvenir).
        res = D.traiter_tour_date(profil, "haha excellent")
        assert res["fin"] is False
        assert res["photo"] == "deux"  # photo souvenir après ce beat

        # Dernier beat livré → conclusion : archivage + points.
        res = D.traiter_tour_date(profil, "tu me raconteras tout !")
        assert res["fin"] is True
        assert res["points"] == D.POINTS_CONCLUSION
        assert profil["date"] is None
        assert "rdv_cafe" in profil["dates_historique"]
        assert profil["last_date_at"]

    def test_moment_non_reconnu_scene_par_defaut(self):
        profil = _profil()
        _force_date(profil, "rdv_cafe")
        D.traiter_tour_date(profil, "avec plaisir !")   # beat 0
        D.traiter_tour_date(profil, "super !")          # beat 1 (question)
        res = D.traiter_tour_date(profil, "comme tu veux !")  # moment
        assert res["fin"] is False
        assert profil["date"]["moment_resolu"] is True

    def test_moment_cle_options_coherentes(self):
        """Chaque scénario à « moment » a ses options détectables et une
        scène par défaut."""
        for scen in D.BANQUE_DATES:
            for beat in scen.get("beats", []):
                moment = beat.get("moment")
                if moment:
                    assert moment.get("options") and moment.get("scenes")
                    assert "_defaut" in moment["scenes"]

    def test_dates_distance_sans_photo(self):
        """Activités à distance : aucune photo (et aucun beat photo)."""
        for scen in D.BANQUE_DATES:
            if scen.get("mode") == "distance":
                assert scen.get("photo") is None
                for beat in scen.get("beats", []):
                    assert beat.get("photo") is None

    def test_dates_presentiel_ont_photo_souvenir(self):
        for scen in D.BANQUE_DATES:
            if scen.get("mode") == "presentiel":
                assert scen.get("photo") == "deux"


class TestDirectivesSansFuite:
    def test_directives_ne_mentionnent_jamais_la_mecanique_brute(self):
        profil = _profil()
        _force_date(profil)
        res = D.traiter_tour_date(profil, "avec plaisir !")
        # Les directives sont adressées au LLM, jamais au joueur : elles
        # sont internes. Le joueur ne voit que le texto du personnage.
        assert res["directive"].startswith("[")
        assert "SCÈNE À VIVRE" in res["directive"]
        assert "ne mentionne jamais" in res["directive"].lower()

    def test_instruction_distance_meme_au_neutre(self):
        """Un scénario à distance reste jouable au neutre SANS jamais
        décrire une rencontre physique."""
        profil = _profil(stage="neutre")
        _force_date(profil, "film_sync")
        res = D.traiter_tour_date(profil, "bonne idée, ça me va !")
        assert "À DISTANCE" in res["directive"]
        assert "JAMAIS une rencontre physique" in res["directive"]
