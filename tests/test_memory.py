# Tests des souvenirs — parsing défensif JSON, cosinus, fallback sans embedder.

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.relation.memory import (  # noqa: E402
    MemoryStore,
    cosine,
    parse_facts,
)


class TestParseFacts:
    def test_json_valide_dans_bloc_markdown(self):
        out = parse_facts('```json\n["aime le cinéma", "travaille chez Danone"]\n```')
        assert out == ["aime le cinéma", "travaille chez Danone"]

    def test_json_brut(self):
        assert parse_facts('["a un chat"]') == ["a un chat"]

    def test_items_non_string_filtres(self):
        assert parse_facts('["ok", 42, null, {"x":1}]') == ["ok"]

    def test_garbage_renvoie_vide_sans_crash(self):
        for bad in ("", "pas du json {", "[incomplet", "null"):
            assert parse_facts(bad) == []

    def test_limite_nombre(self):
        many = "[" + ",".join(f'"f{i}"' for i in range(50)) + "]"
        assert len(parse_facts(many)) <= 8

    def test_troncature_faits_longs(self):
        long = "x" * 1000
        facts = parse_facts(f'["{long}"]')
        assert len(facts[0]) <= 400


class TestCosine:
    def test_vecteurs_identiques(self):
        v = [1.0, 0.0, 1.0]
        assert abs(cosine(v, v) - 1.0) < 1e-9

    def test_orthogonaux(self):
        assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_opposes(self):
        assert abs(cosine([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-9

    def test_vecteur_nul_sans_division_zero(self):
        assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_longueurs_differentes(self):
        assert cosine([1.0], [1.0, 2.0]) == 0.0


class TestFallbackSansEmbedder:
    """Sans serveur d'embeddings : stockage sans vecteur + rappel récent."""

    def test_add_and_retrieve_recent(self):
        store = MemoryStore(None)
        profile = {}
        added = asyncio.run(store.add_facts(profile, ["fait un", "fait deux"]))
        assert added == 2
        hits = asyncio.run(store.retrieve(profile, "peu importe"))
        # Fallback = plus récents en dernier (ordre chronologique).
        assert hits[-1] == "fait deux"

    def test_dedoublonnage_insensible_casse_espaces(self):
        store = MemoryStore(None)
        profile = {}
        asyncio.run(store.add_facts(profile, ["Aime les chats"]))
        added = asyncio.run(store.add_facts(profile, ["  aime   LES chats  "]))
        assert added == 0
        assert len(profile["memories"]) == 1

    def test_cap_fifo_garde_les_plus_recents(self):
        store = MemoryStore(None, max_memories=5)
        profile = {}
        for i in range(10):
            asyncio.run(store.add_facts(profile, [f"memo-{i}"]))
        texts = [m["fact"] for m in profile["memories"]]
        assert len(texts) == 5
        assert texts[-1] == "memo-9"  # le plus récent en fin de liste

    def test_chaine_vide_rejetee(self):
        store = MemoryStore(None)
        profile = {}
        assert asyncio.run(store.add_facts(profile, ["", "   ", None])) == 0

    def test_retrieve_profil_vide(self):
        store = MemoryStore(None)
        assert asyncio.run(store.retrieve({}, "query")) == []
