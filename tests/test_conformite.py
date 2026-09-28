# Tests de CONFORMITÉ du jeu — vérifie les invariants de conception :
#
#  1. Stades relationnels : pour TOUT score 0-1000, le prompt reçu par le LLM
#     contient le bon stade + la bonne consigne (l'IA ne peut jamais voir un
#     autre stade que celui calculé côté serveur) ;
#  2. Parcours relationnel complet : montée froid→proche par messages aimables,
#     descente vers rejet par insultes, bornes de delta, cohérence score/stade ;
#  3. Scénarios : conformité des données (25 personnages) + gates de stade ;
#  4. Mémoire : rappel sémantique, fail-safe, cadence d'extraction ;
#  5. Garde-fous photos par stade + initiative photo ;
#  6. Messages proactifs conformes (jamais au stade rejet) ;
#  7. Anti-triche : le LLM n'a aucun outil, la mécanique est serveur.
#
# Ces tests exercent la couche DÉTERMINISTE (celle que le LLM ne peut pas
# contourner). Le comportement verbal du modèle n'est pas testé ici (aucun
# réseau en suite de tests) : c'est le prompt qui définit son contrat.

import asyncio
import random
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import load_config  # noqa: E402
from server.image import helpers as img_helpers  # noqa: E402
from server.llm.prompt_builder import PromptBuilder  # noqa: E402
from server.relation import presets as P  # noqa: E402
from server.relation import scoring  # noqa: E402
from server.relation.memory import MemoryStore  # noqa: E402
from server.relation.scoring import compute_delta  # noqa: E402
from server.relation.stages import (  # noqa: E402
    STAGE_INSTRUCTIONS,
    STAGE_LABELS,
    STAGE_ORDER,
    can_play_stage,
    compute_stage,
)
from server.relation.state import RelationState  # noqa: E402


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _profil(score: int) -> dict:
    st = compute_stage(score)
    return {
        "meta": {"session_id": "conf", "user": "u"},
        "character": {"preset_id": None, "name": "Clara", "age": "28",
                      "gender": "F"},
        "relationship_score": score,
        "relationship_stage": st,
    }


def _fresh_profile(preset_id: str) -> dict:
    return {
        "meta": {"session_id": "conf", "user": "u"},
        "character": {"preset_id": preset_id, "name": "Test"},
        "relationship_score": 100,
        "relationship_stage": "froid",
        "interaction_count": 0,
        "event_history": [],
        "event_attempts": {},
        "last_event_at": None,
        "last_injected_event_id": None,
    }


_SCORES_BALAYAGE = [
    0, 1, 50, 99, 100, 150, 199, 200, 300, 399,
    400, 500, 599, 600, 700, 799, 800, 900, 1000,
]


# =========================================================================== #
#  1. STADES ↔ PROMPT LLM — le modèle ne voit jamais un autre stade
# =========================================================================== #
class TestConformiteStadesPrompt:
    """Le prompt système est le SEUL canal par lequel le LLM connaît le stade.

    Conformité : pour chaque score possible, le prompt doit contenir
    exactement la consigne du stade courant — et aucune autre.
    """

    def setup_method(self):
        self.pb = PromptBuilder(load_config())

    def _system_msg(self, score: int) -> str:
        return self.pb.build_system_message(_profil(score), [], None)

    def test_balayage_complet_stade_et_consigne_corrects(self):
        signatures = {
            s: STAGE_INSTRUCTIONS[s][:60] for s in STAGE_ORDER
        }
        for score in _SCORES_BALAYAGE:
            st = compute_stage(score)
            msg = self._system_msg(score)
            # Le libellé du bon stade est affiché.
            assert STAGE_LABELS[st] in msg, f"score {score} : libellé absent"
            # Le score exact est affiché.
            assert f"{score}/1000" in msg, f"score {score} : score absent"
            # La consigne exacte du bon stade est injectée.
            assert STAGE_INSTRUCTIONS[st] in msg, f"score {score} : consigne absente"
            # AUCUNE consigne d'un autre stade ne fuit dans le prompt.
            for autre in STAGE_ORDER:
                if autre != st:
                    assert signatures[autre] not in msg, (
                        f"score {score} ({st}) : fuite de la consigne « {autre} »"
                    )

    def test_consignes_distinctes_et_non_vides(self):
        vals = list(STAGE_INSTRUCTIONS.values())
        assert all(isinstance(v, str) and len(v) > 40 for v in vals)
        assert len(set(vals)) == len(STAGE_ORDER)

    def test_hierarchy_consigne_prevalle(self):
        """La consigne doit affirmer sa prévalence sur personnalité/demandes."""
        for score in _SCORES_BALAYAGE:
            msg = self._system_message_relation(score)
            assert "PRÉVAUT" in msg
            assert "vérité système" in msg

    def _system_message_relation(self, score: int) -> str:
        return self.pb.build_relation_block(_profil(score))

    def test_contenu_conforme_par_stade(self):
        """Le TEXTE des consignes respecte la gradation prévue du jeu."""
        rej = STAGE_INSTRUCTIONS["rejet"]
        froid = STAGE_INSTRUCTIONS["froid"]
        reserve = STAGE_INSTRUCTIONS["reserve"]
        neutre = STAGE_INSTRUCTIONS["neutre"]
        chaleureux = STAGE_INSTRUCTIONS["chaleureux"]
        proche = STAGE_INSTRUCTIONS["proche"]
        # rejet : refus actif, rien d'autre.
        assert "INTERDIT" in rej and "refus" in rej.lower()
        # froid / réservé : inconnus, sexualité refusée.
        for txt in (froid, reserve):
            assert "sexualité" in txt.lower()
            assert "invitation" in txt.lower() or "souper" in txt.lower()
        # neutre : ouvert mais sollicitation sexuelle refusée.
        assert "sollicitation sexuelle" in neutre.lower()
        # chaleureux : complicité mais pas de descriptions explicites.
        assert "explicites" in chaleureux.lower()
        # proche : couple uni, aucun sujet tabou.
        assert "tabou" in proche.lower()

    def test_stade_inconnu_consigne_vide_sans_crash(self):
        assert STAGE_INSTRUCTIONS.get("stade-fantome", "") == ""


# =========================================================================== #
#  2. PARCOURS RELATIONNEL COMPLET
# =========================================================================== #
COMPLIMENT = "Merci beaucoup, c'est super génial ! Bravo, magnifique, adorable !"
INSULTE_DIRIGEE = "tu es une stupide connasse débile idiote, je te déteste"


class TestConformiteParcours:
    def test_montee_complete_froid_vers_proche(self):
        """Une conversation aimable mène de « froid » (100) à « proche » (800+)."""
        score = 100
        stades = [compute_stage(score)]
        for _ in range(200):
            score += compute_delta(COMPLIMENT, "...", compute_stage(score))
            stades.append(compute_stage(score))
            if score >= 800:
                break
        assert score >= 800, "la relation doit pouvoir atteindre « proche »"
        # Les stades sont traversés dans l'ordre exact, sans jamais sauter
        # ni redescendre.
        attendus = ["froid", "reserve", "neutre", "chaleureux", "proche"]
        positions = [attendus.index(s) for s in stades]
        assert positions == sorted(positions), f"montée désordonnée : {stades}"
        assert set(stades) == set(attendus), (
            f"stade manqué : {set(attendus) - set(stades)}"
        )

    def test_descente_proche_vers_rejet(self):
        """Des insultes répétées font chuter la relation jusqu'au rejet."""
        score = 900
        for _ in range(200):
            score += compute_delta(INSULTE_DIRIGEE, "...", compute_stage(score))
            if score < 100:
                break
        assert score < 100, "les insultes doivent mener au stade « rejet »"
        assert compute_stage(score) == "rejet"

    def test_bornes_delta_sur_corpus(self):
        """Tous les deltas restent dans [-20 ; +16] quel que soit le message."""
        corpus = [
            "", "salut", "ça va ?", "merci !!", "tu es géniale",
            "tu es vraiment une personne magnifique et géniale super",
            INSULTE_DIRIGEE, "cette merde ne marche pas", "ok", "…",
            "j'adore merci super parfait excellent bravo formidable",
            "pardon désolé je m'excuse tu as raison",
            "envoie une photo de toi", "déshabille-toi", "montre-toi nue",
            "je cherche dans l'annuaire", "quel menu recommandes-tu ?",
            "x" * 500,
        ]
        for msg in corpus:
            for st in STAGE_ORDER:
                d = compute_delta(msg, "...", st)
                assert -20 <= d <= 16, f"delta {d} hors bornes pour {msg!r} ({st})"

    def test_message_neutre_progresse_a_tous_les_stades(self):
        for st in STAGE_ORDER:
            assert compute_delta("je cherche dans l'annuaire", "...", st) == 1

    def test_insistance_penalisee_sous_neutre_uniquement(self):
        msg = "envoie une photo de toi"
        for st in ("rejet", "froid", "reserve", "neutre"):
            assert compute_delta(msg, "...", st) <= -6
        for st in ("chaleureux", "proche"):
            assert compute_delta(msg, "...", st) >= 1

    def test_coherence_score_stade_apres_deltas_aleatoires(self, tmp_path):
        """Propriété : le stade stocké reflète TOUJOURS le score (clamp 0-1000)."""
        st = RelationState(str(tmp_path), "prop")
        rng = random.Random(42)
        for seed_path in range(8):
            profile = _profil(rng.choice(_SCORES_BALAYAGE))
            for _ in range(60):
                delta = rng.randint(-20, 16)
                st.set_score(profile, profile["relationship_score"] + delta)
                score = profile["relationship_score"]
                assert 0 <= score <= 1000
                assert profile["relationship_stage"] == compute_stage(score)

    def test_seuils_stades_exactement_respectes(self):
        paires = [(99, "rejet"), (100, "froid"), (199, "froid"),
                  (200, "reserve"), (399, "reserve"), (400, "neutre"),
                  (599, "neutre"), (600, "chaleureux"), (799, "chaleureux"),
                  (800, "proche")]
        for score, st in paires:
            assert compute_stage(score) == st

    def test_ordre_stades_coherent(self):
        assert STAGE_ORDER == [
            "rejet", "froid", "reserve", "neutre", "chaleureux", "proche"
        ]
        assert list(STAGE_LABELS) == STAGE_ORDER


# =========================================================================== #
#  3. SCÉNARIOS — conformité des données + gates pour les 25 personnages
# =========================================================================== #
class TestConformiteScenariosDonnees:
    """Les 275 scénarios doivent respecter la matrice de gates du jeu."""

    def test_25_personnages_avec_scenario_A_K(self):
        blocks = P.load_preset_events()
        chars = P.load_preset_characters()
        assert len(chars) >= 25
        assert len(blocks) >= 25
        for c in chars:
            evs = blocks.get(c["id"], [])
            assert len(evs) == 11, f"{c['id']} : {len(evs)} scénarios (attendu 11)"
            assert sorted(e["letter"] for e in evs) == list("ABCDEFGHIJK")

    def test_ids_uniques_et_prefixes(self):
        vus = set()
        for cid, evs in P.load_preset_events().items():
            for e in evs:
                eid = e["event_id"]
                assert eid not in vus, f"event_id dupliqué : {eid}"
                vus.add(eid)
                assert cid in eid, f"{eid} ne référence pas son personnage {cid}"

    def test_matrice_min_stage(self):
        """A-H : pas de gate ; I/J : chaleureux ; K : proche."""
        attendu = dict.fromkeys("ABCDEFGH", None)
        attendu.update({"I": "chaleureux", "J": "chaleureux", "K": "proche"})
        for cid, evs in P.load_preset_events().items():
            for e in evs:
                assert e.get("min_stage") == attendu[e["letter"]], (
                    f"{cid}/{e['letter']} : min_stage={e.get('min_stage')!r}"
                )

    def test_tones_conformes_aux_lettres(self):
        for cid, evs in P.load_preset_events().items():
            for e in evs:
                if e["letter"] in "ABCDEFGHIJ":
                    assert e["tone"] in ("success", "tragedy", "comedy",
                                         "intimate_slow_build",
                                         "intimate_consummation"), (
                        f"{cid}/{e['letter']} : tone inattendu {e['tone']!r}"
                    )
                else:  # K
                    assert e["tone"] == "finale"

    def test_titres_et_corps_non_vides(self):
        for cid, evs in P.load_preset_events().items():
            for e in evs:
                assert isinstance(e.get("title"), str) and e["title"].strip()
                assert isinstance(e.get("body"), str) and len(e["body"]) > 30


class TestConformiteGatesTousPersonnages:
    """Sweep des gates de sélection pour CHAQUE personnage."""

    def test_aucun_scenario_avant_neutre(self):
        for c in P.load_preset_characters():
            profile = _fresh_profile(c["id"])
            for score, st in ((0, "rejet"), (100, "froid"),
                              (150, "froid"), (250, "reserve"),
                              (399, "reserve")):
                assert P.get_pending_event(profile, st, cooldown_hours=0) is None, (
                    f"{c['id']} : scénario injecté au stade {st} (score {score})"
                )

    def test_premier_scenario_a_neutre_est_non_intime(self):
        for c in P.load_preset_characters():
            profile = _fresh_profile(c["id"])
            pending = P.get_pending_event(profile, "neutre", cooldown_hours=0)
            assert pending is not None, f"{c['id']} : rien à « neutre »"
            assert pending["letter"] in "ABCDEFGH"

    def test_intimes_I_J_bloques_a_neutre(self):
        for c in P.load_preset_characters():
            profile = _fresh_profile(c["id"])
            for e in P.get_events_for_character(c["id"]):
                if e["letter"] in "ABCDEFGH":
                    P.mark_event_consumed(profile, e["event_id"])
            pending = P.get_pending_event(profile, "neutre", cooldown_hours=0)
            assert pending is None, (
                f"{c['id']} : scénario intime sorti à « neutre » ({pending})"
            )

    def test_intimes_I_J_debloques_a_chaleureux_puis_prioritaires(self):
        for c in P.load_preset_characters():
            profile = _fresh_profile(c["id"])
            # Priorité intime : I/J passent AVANT les A-H restants.
            pending = P.get_pending_event(profile, "chaleureux", cooldown_hours=0)
            assert pending is not None and pending["letter"] in ("I", "J"), (
                f"{c['id']} : priorité intime non respectée à « chaleureux »"
            )
            P.mark_event_consumed(profile, pending["event_id"])
            # L'autre scénario intime sort ensuite, toujours avant les A-H.
            pending = P.get_pending_event(profile, "chaleureux", cooldown_hours=0)
            assert pending is not None and pending["letter"] in ("I", "J"), (
                f"{c['id']} : second intime attendu, reçu {pending and pending['letter']}"
            )

    def test_K_exige_proche_et_tous_A_J(self):
        for c in P.load_preset_characters():
            evs = P.get_events_for_character(c["id"])
            profile = _fresh_profile(c["id"])
            # Cas 1 : proche mais il reste un A-J → K invisible.
            others = [e for e in evs if e["letter"] != "K"]
            for e in others[:-1]:
                P.mark_event_consumed(profile, e["event_id"])
            pending = P.get_pending_event(profile, "proche", cooldown_hours=0)
            assert pending is None or pending["letter"] != "K"
            # Cas 2 : chaleureux + tout A-J consommé → K toujours invisible.
            for e in others:
                P.mark_event_consumed(profile, e["event_id"])
            assert P.get_pending_event(
                profile, "chaleureux", cooldown_hours=0
            ) is None
            # Cas 3 : proche + tout consommé → K enfin jouable.
            pending = P.get_pending_event(profile, "proche", cooldown_hours=0)
            assert pending is not None and pending["letter"] == "K", (
                f"{c['id']} : finale K injouable alors que tout est consommé"
            )

    def test_scenario_consomme_ne_revient_pas(self):
        c = P.load_preset_characters()[0]
        profile = _fresh_profile(c["id"])
        first = P.get_pending_event(profile, "neutre", cooldown_hours=0)
        P.mark_event_consumed(profile, first["event_id"])
        second = P.get_pending_event(profile, "neutre", cooldown_hours=0)
        assert second["event_id"] != first["event_id"]

    def test_perso_custom_sans_scenarios(self):
        profile = _fresh_profile(None)
        profile["character"]["preset_id"] = None
        profile["relationship_stage"] = "proche"
        assert P.get_pending_event(profile, "proche", cooldown_hours=0) is None

    def test_can_play_stage_conservateur(self):
        # Stade inconnu → refus (garde-fou).
        assert can_play_stage("neutre", "stade-inconnu") is False
        assert can_play_stage("gate-inconnue", "neutre") is False
        assert can_play_stage(None, "froid") is True


# =========================================================================== #
#  4. MÉMOIRE — rappel sémantique, fail-safe, cadence d'extraction
# =========================================================================== #
class _FakeEmbedder:
    """Embedder déterministe : [nb « chat », nb « chien », nb « travail »]."""

    MOTS = ["chat", "chien", "travail"]

    def _vec(self, t: str) -> list[float]:
        low = (t or "").lower()
        v = [float(low.count(m)) for m in self.MOTS]
        n = sum(v) or 1.0
        return [x / n for x in v]

    async def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    async def embed_query(self, text):
        return self._vec(text)


class _EmbedderCassé:
    async def embed_documents(self, texts):
        raise RuntimeError("embeddings indisponibles")

    async def embed_query(self, text):
        raise RuntimeError("embeddings indisponibles")


class TestConformiteMemoire:
    def test_rappel_semantique_range_par_pertinence(self):
        store = MemoryStore(_FakeEmbedder())
        profile = {}
        asyncio.run(store.add_facts(
            profile, ["A un chat nommé Rex", "Parle de son travail chez Acme"]
        ))
        hits = asyncio.run(store.retrieve(profile, "ton chat va bien ?"))
        assert hits, "le rappel ne doit jamais être vide s'il y a des souvenirs"
        assert "A un chat nommé Rex" in hits[0]

    def test_rappel_filtre_par_seuil_similarite(self):
        store = MemoryStore(_FakeEmbedder())
        profile = {}
        asyncio.run(store.add_facts(profile, ["Parle de son travail chez Acme"]))
        # Aucun mot partagé avec la requête → fallback (2 plus récents).
        hits = asyncio.run(store.retrieve(
            profile, "quelle est ta couleur préférée ?",
            min_similarity=0.99,
        ))
        assert hits == ["Parle de son travail chez Acme"]  # fallback continuité

    def test_ajout_sur_embedder_casse_fail_safe(self):
        """Embeddings indisponibles : les faits restent stockés (sans vecteur)."""
        store = MemoryStore(_EmbedderCassé())
        profile = {}
        added = asyncio.run(store.add_facts(profile, ["S'appelle Marc"]))
        assert added == 1
        assert profile["memories"][0]["embedding"] is None
        # Rappel : fallback récent, jamais de crash.
        hits = asyncio.run(store.retrieve(profile, "n'importe quoi"))
        assert hits == ["S'appelle Marc"]

    def test_extraction_cadence(self, monkeypatch):
        """L'extraction de souvenirs ne tourne que tous les N tours."""
        from server.main import app, _extract_memories_if_due

        class _FakeLLM:
            def __init__(self, content):
                self.content = content
                self.calls = 0

            async def chat(self, messages, **kw):
                self.calls += 1

                class _R:
                    pass

                r = _R()
                r.content = self.content
                return r

        cfg = load_config()
        cfg.relation.summarize_every_turns = 10
        fake = _FakeLLM('["S\'appelle Marc", "A un chat nommé Rex"]')
        monkeypatch.setattr(app.state, "cfg", cfg, raising=False)
        monkeypatch.setattr(app.state, "client", fake, raising=False)
        monkeypatch.setattr(
            app.state, "memories", MemoryStore(None), raising=False
        )

        # Tour 9 → pas d'extraction.
        profile = {"interaction_count": 9, "memories": []}
        assert asyncio.run(
            _extract_memories_if_due("sid", profile, "salut", "hey")
        ) == 0
        assert fake.calls == 0 and not profile["memories"]

        # Tour 10 → extraction + faits ajoutés (retour > 0 : le pipeline
        # doit repersistancer le profil, sinon les souvenirs sont perdus).
        profile = {"interaction_count": 10, "memories": []}
        ajout = asyncio.run(
            _extract_memories_if_due("sid", profile, "salut", "hey")
        )
        assert fake.calls == 1 and ajout == 2
        facts = [m["fact"] for m in profile["memories"]]
        assert "S'appelle Marc" in facts and "A un chat nommé Rex" in facts

        # Tour 11 → rien.
        profile = {"interaction_count": 11, "memories": []}
        assert asyncio.run(
            _extract_memories_if_due("sid", profile, "salut", "hey")
        ) == 0
        assert fake.calls == 1

    def test_extraction_robuste_aux_reponses_invalides(self, monkeypatch):
        from server.main import app, _extract_memories_if_due

        class _FakeLLM:
            def __init__(self, content):
                self.content = content
                self.calls = 0

            async def chat(self, messages, **kw):
                self.calls += 1

                class _R:
                    pass

                r = _R()
                r.content = self.content
                return r

        cfg = load_config()
        cfg.relation.summarize_every_turns = 1
        fake = _FakeLLM("je ne sais pas, pas de json ici")
        monkeypatch.setattr(app.state, "cfg", cfg, raising=False)
        monkeypatch.setattr(app.state, "client", fake, raising=False)
        monkeypatch.setattr(
            app.state, "memories", MemoryStore(None), raising=False
        )
        profile = {"interaction_count": 4, "memories": []}
        asyncio.run(_extract_memories_if_due("sid", profile, "salut", "hey"))
        assert fake.calls == 1 and profile["memories"] == []

    def test_extraction_sur_llm_en_panne_ne_crash_pas(self, monkeypatch):
        from server.main import app, _extract_memories_if_due

        class _LLMMort:
            async def chat(self, messages, **kw):
                raise RuntimeError("modèle injoignable")

        cfg = load_config()
        cfg.relation.summarize_every_turns = 1
        monkeypatch.setattr(app.state, "cfg", cfg, raising=False)
        monkeypatch.setattr(app.state, "client", _LLMMort(), raising=False)
        monkeypatch.setattr(
            app.state, "memories", MemoryStore(None), raising=False
        )
        profile = {"interaction_count": 5, "memories": []}
        asyncio.run(_extract_memories_if_due("sid", profile, "salut", "hey"))
        assert profile["memories"] == []

    def test_memories_injectees_dans_prompt_avec_consigne(self):
        pb = PromptBuilder(load_config())
        msg = pb.build_system_message(
            _profil(500), ["S'appelle Marc", "A un chat nommé Rex"], None
        )
        assert "S'appelle Marc" in msg
        assert "A un chat nommé Rex" in msg
        assert "SOUVENIRS" in msg
        assert "sans jamais mentionner" in msg
        # Sans souvenir : pas de bloc.
        msg_vide = pb.build_system_message(_profil(500), [], None)
        assert "SOUVENIRS" not in msg_vide


# =========================================================================== #
#  5. PHOTOS — garde-fous par stade + initiative
# =========================================================================== #
class TestConformitePhotos:
    def test_refus_exactement_avant_neutre(self):
        """Conformité README : photos refusées aux stades rejet/froid/réservé."""
        assert set(img_helpers.REFUSALS_BY_STAGE) == {"rejet", "froid", "reserve"}
        for st in ("rejet", "froid", "reserve"):
            assert img_helpers.REFUSALS_BY_STAGE[st].strip()
        # Aucun refus à partir de « neutre ».
        for st in ("neutre", "chaleureux", "proche"):
            assert st not in img_helpers.REFUSALS_BY_STAGE

    def test_matrice_tenue_par_stade(self):
        char = {"name": "Clara", "age": "28", "gender": "F",
                "appearance": "brune", "interests": "cinéma"}
        # réservé / neutre : entièrement habillée.
        for st in ("reserve", "neutre"):
            p = img_helpers.photo_prompt_for_stage(char, st)
            assert "fully dressed" in p, f"stade {st} : tenue sobre absente"
        # chaleureux : lingerie ok mais jamais nue.
        p = img_helpers.photo_prompt_for_stage(char, "chaleureux")
        assert "never nude" in p
        assert "fully dressed" not in p
        # proche : sans restriction.
        p = img_helpers.photo_prompt_for_stage(char, "proche")
        assert "unrestricted" in p

    def test_sanitisation_nudite_hors_proche(self):
        for st in ("rejet", "froid", "reserve", "neutre", "chaleureux"):
            s = img_helpers.sanitize_scene("nude on the bed", st)
            assert "nude" not in s.lower()
        assert "nude" in img_helpers.sanitize_scene("nude on the bed", "proche").lower()

    def test_initiative_photo_stades_autorises(self, monkeypatch):
        """L'initiative photo n'est possible qu'aux stades neutre et +."""
        import server.main as M

        cfg = load_config()
        cfg.image.enabled = True
        cfg.image.initiative_enabled = True
        cfg.image.initiative_chance_turn = 1.0  # réussite garantie
        monkeypatch.setattr(M, "cfg", cfg, raising=False)
        monkeypatch.setattr(M.app.state, "image", object(), raising=False)

        for st, attendu in (("rejet", False), ("froid", False),
                            ("reserve", False), ("neutre", True),
                            ("chaleureux", True), ("proche", True)):
            profile = _profil({"rejet": 50, "froid": 150, "reserve": 300,
                               "neutre": 500, "chaleureux": 700,
                               "proche": 900}[st])
            assert M._initiative_photo_due(profile) is attendu, f"stade {st}"

        # Probabilité nulle → jamais d'initiative.
        cfg.image.initiative_chance_turn = 0.0
        assert M._initiative_photo_due(_profil(500)) is False

        # Backends désactivés → jamais (même au stade proche).
        cfg.image.enabled = False
        assert M._initiative_photo_due(_profil(900)) is False

    def test_initiative_photo_sans_backend_image(self, monkeypatch):
        import server.main as M

        cfg = load_config()
        cfg.image.enabled = True
        cfg.image.initiative_enabled = True
        cfg.image.initiative_chance_turn = 1.0
        monkeypatch.setattr(M, "cfg", cfg, raising=False)
        monkeypatch.setattr(
            M.app.state, "image", None, raising=False
        )
        assert M._initiative_photo_due(_profil(500)) is False


# =========================================================================== #
#  6. MESSAGES PROACTIFS — conformité des contenus
# =========================================================================== #
class TestConformiteProactifs:
    def test_jamais_de_proactif_au_stade_rejet(self):
        from server.main import PROACTIVE_FALLBACKS

        assert "rejet" not in PROACTIVE_FALLBACKS
        assert set(PROACTIVE_FALLBACKS) == {
            "froid", "reserve", "neutre", "chaleureux", "proche"
        }

    def test_fallbacks_non_vides_et_varies(self):
        from server.main import PROACTIVE_FALLBACKS

        for st, msgs in PROACTIVE_FALLBACKS.items():
            assert len(msgs) >= 3, f"{st} : pas assez de variantes"
            assert all(isinstance(m, str) and m.strip() for m in msgs)
            assert len(set(msgs)) == len(msgs), f"{st} : doublons"

    def test_gradation_emotionnelle_complete(self):
        from server.main import PROACTIVE_ESCALATION

        assert len(PROACTIVE_ESCALATION) == 5
        for bucket in PROACTIVE_ESCALATION:
            assert bucket and all(m.strip() for m in bucket)
        # La gradation monte : le dernier tonde à la rupture, le 2e s'inquiète.
        assert any("inquiét" in m.lower() for m in PROACTIVE_ESCALATION[1])
        assert any(
            m.lower().startswith(("oubli", "fini", "adieu"))
            or "page" in m.lower()
            for m in PROACTIVE_ESCALATION[4]
        )

    def test_penalite_proactive_conforme(self):
        cfg = load_config()
        assert cfg.relation.proactive_penalty == 15
        assert cfg.relation.proactive_after_hours == 24.0
        assert cfg.relation.proactive_interval_hours == 24.0


# =========================================================================== #
#  7. ANTI-TRICHE — le LLM ne contrôle AUCUNE mécanique
# =========================================================================== #
class TestConformiteAntiTriche:
    def setup_method(self):
        self.pb = PromptBuilder(load_config())

    def test_note_automatisations_toujours_presente(self):
        for score in (50, 300, 500, 700, 900):
            msg = self.pb.build_system_message(_profil(score), [], None)
            assert "AUCUN outil" in msg
            assert "recalculé côté serveur" in msg
            assert "UNIQUEMENT ce que ton personnage" in msg

    def test_event_block_ne_revele_jamais_son_identifiant(self):
        ev = {
            "event_id": "clara_moreau_C",
            "letter": "C",
            "title": "La crise de la page blanche",
            "tone": "success",
            "min_stage": None,
            "body": "Clara bloque sur une couverture de livre jeunesse.",
        }
        bloc = self.pb.build_event_block(ev)
        assert "clara_moreau_C" not in bloc      # id jamais montré
        # Consigne impérative anti-méta (ne pas citer la mécanique).
        assert "OBLIGATOIRE" in bloc
        assert "JAMAIS" in bloc
        assert "La crise de la page blanche" in bloc

    def test_event_block_vide_sans_scenario(self):
        assert self.pb.build_event_block(None) == ""

    def test_aucun_tool_expose_dans_le_prompt(self):
        msg = self.pb.build_system_message(_profil(500), [], None)
        # La note explicite au modèle qu'il n'a rien à évaluer.
        assert "n'as AUCUN outil" in msg
        assert "AUCUNE évaluation" in msg

    def test_decroissance_conforme_config(self):
        cfg = load_config()
        now = datetime(2026, 9, 13, 12, 0, 0)
        last = datetime(2026, 9, 8, 12, 0, 0).isoformat()  # 5 jours : 2 j comptés
        score, applied = scoring.apply_time_decay(
            500, last, now,
            days_grace=cfg.relation.decay_days_grace,
            points_per_day=cfg.relation.decay_points_per_day,
            max_loss=cfg.relation.decay_max_loss,
        )
        assert applied and score == 480
        assert cfg.relation.decay_days_grace == 3
        assert cfg.relation.decay_points_per_day == 10
        assert cfg.relation.decay_max_loss == 150


# =========================================================================== #
#  8. PERSISTANCE — état relationnel cohérent sur disque
# =========================================================================== #
class TestConformitePersistance:
    def test_score_et_stade_persistes(self, tmp_path):
        st = RelationState(str(tmp_path), "conf1")
        profile = st.load()
        assert profile["relationship_score"] == 100
        assert profile["relationship_stage"] == "froid"
        st.set_score(profile, 650)
        assert st.save(profile) is None
        # Rechargement à froid : mêmes valeurs.
        profile2 = RelationState(str(tmp_path), "conf1").load()
        assert profile2["relationship_score"] == 650
        assert profile2["relationship_stage"] == "chaleureux"

    def test_set_score_marque_le_stade_toujours(self, tmp_path):
        st = RelationState(str(tmp_path), "conf2")
        profile = st.load()
        for score in (0, 99, 100, 450, 799, 1000):
            st.set_score(profile, score, mark_interaction=False)
            assert profile["relationship_stage"] == compute_stage(score)
