# Tests des presets et scénarios — gates de stade, cooldown, consommation.

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.relation import presets as P  # noqa: E402
from server.relation.stages import compute_stage  # noqa: E402

# Les timestamps de last_event_at sont comparés à datetime.utcnow() côté
# serveur : les tests utilisent donc UTC également.


def _utcnow() -> datetime:
    return datetime.utcnow()


def _utcoh(hours: float) -> str:
    return (_utcnow() - timedelta(hours=hours)).isoformat()


def _fresh_profile(preset_id: str = None) -> dict:
    """Profil minimal pour tester les gates sans disque."""
    if preset_id is None:
        chars = P.load_preset_characters()
        preset_id = chars[0]["id"]
    return {
        "meta": {"session_id": "test", "user": "x"},
        "character": {"preset_id": preset_id, "name": "Test"},
        "relationship_score": 100,
        "relationship_stage": "froid",
        "interaction_count": 0,
        "event_history": [],
        "event_attempts": {},
        "last_event_at": None,
        "last_injected_event_id": None,
    }


class TestChargement:
    def test_personnages_presents(self):
        chars = P.load_preset_characters()
        assert len(chars) >= 20
        c = P.get_preset_character(chars[0]["id"])
        assert c is not None and c["id"] == chars[0]["id"]

    def test_scenarios_indexes(self):
        events = P.load_preset_events()
        assert len(events) >= 20  # au moins un jeu A-K par personnage
        for cid, evs in events.items():
            letters = {e["letter"] for e in evs}
            assert letters <= set("ABCDEFGHIJK")

    def test_preset_inconnu(self):
        assert P.get_preset_character("nimporte-quoi") is None


class TestGates:
    def test_aucun_event_sous_neutre(self):
        profile = _fresh_profile()
        profile["relationship_score"] = 100
        profile["relationship_stage"] = compute_stage(100)
        assert P.get_pending_event(profile, "froid", cooldown_hours=24) is None

    def test_event_des_neutre_si_historique_vierge(self):
        profile = _fresh_profile()
        profile["relationship_score"] = 500
        profile["relationship_stage"] = "neutre"
        # Cooldown nul pour le test (jamais d'event injecté).
        pending = P.get_pending_event(profile, "neutre", cooldown_hours=0)
        if P.load_preset_events().get(profile["character"]["preset_id"]):
            assert pending is not None
            # min_stage peut être None (scénarios A-H jouables dès « neutre »).
            assert pending.get("min_stage") in ("neutre", "chaleureux", "proche", None)

    def test_gate_I_J_chaleureux(self):
        """Les events intimes I/J ne sortent qu'au stade chaleureux."""
        profile = _fresh_profile()
        cid = profile["character"]["preset_id"]
        evs = P.load_preset_events().get(cid, [])
        ij = [e for e in evs if e["letter"] in ("I", "J")]
        if not ij:
            return
        profile["relationship_score"] = 650
        profile["relationship_stage"] = "chaleureux"
        for e in evs:  # consomme tout sauf I/J
            if e["letter"] not in ("I", "J"):
                P.mark_event_consumed(profile, e["event_id"])
        pending = P.get_pending_event(profile, "chaleureux", cooldown_hours=0)
        assert pending is not None and pending["letter"] in ("I", "J")

    def test_gate_K_duale_stricte(self):
        """K exige stade proche ET tous les A-J consommés."""
        profile = _fresh_profile()
        cid = profile["character"]["preset_id"]
        evs = P.load_preset_events().get(cid, [])
        if not any(e["letter"] == "K" for e in evs):
            return
        profile["relationship_score"] = 900
        profile["relationship_stage"] = "proche"
        # Cas 1 : A-J tous consommés sauf un → K bloqué.
        others = [e for e in evs if e["letter"] != "K"]
        for e in others[:-1]:
            P.mark_event_consumed(profile, e["event_id"])
        pending = P.get_pending_event(profile, "proche", cooldown_hours=0)
        assert pending is None or pending["letter"] != "K"
        # Cas 2 : tout consommé → K accessible.
        for e in others:
            P.mark_event_consumed(profile, e["event_id"])
        pending = P.get_pending_event(profile, "proche", cooldown_hours=0)
        assert pending is not None and pending["letter"] == "K"

    def test_cooldown_bloque(self):
        profile = _fresh_profile()
        profile["relationship_score"] = 500
        profile["relationship_stage"] = "neutre"
        first = P.get_pending_event(profile, "neutre", cooldown_hours=0)
        if first is None:
            return
        profile["last_event_at"] = _utcnow().isoformat()
        assert P.get_pending_event(profile, "neutre", cooldown_hours=24) is None
        # Cooldown expiré → à nouveau disponible.
        profile["last_event_at"] = _utcoh(25)
        assert P.get_pending_event(profile, "neutre", cooldown_hours=24) is not None


class TestConsommation:
    def test_mark_consumed(self):
        profile = _fresh_profile()
        evs = P.load_preset_events().get(profile["character"]["preset_id"], [])
        if not evs:
            return
        eid = evs[0]["event_id"]
        assert eid not in profile["event_history"]
        P.mark_event_consumed(profile, eid)
        assert eid in profile["event_history"]

    def test_build_character_from_preset(self):
        chars = P.load_preset_characters()
        built = P.build_character_from_preset(chars[0])
        assert built["name"] == chars[0]["name"]
        assert built["preset_id"] == chars[0]["id"]
        assert isinstance(built.get("appearance"), str)
