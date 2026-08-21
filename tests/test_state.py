# Tests de l'état persistant — écritures atomiques, score, photos, delete.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.relation.state import RelationState  # noqa: E402


class TestRelationState:
    def test_load_vide_profil_defaut(self, tmp_path):
        st = RelationState(str(tmp_path), "abc123")
        profile = st.load()
        assert "_erreur" not in profile
        assert profile["relationship_score"] == 100
        assert profile["relationship_stage"] == "froid"
        assert profile["meta"]["session_id"] == "abc123"
        assert profile["photos"] == []

    def test_save_roundtrip(self, tmp_path):
        st = RelationState(str(tmp_path), "abc123")
        profile = st.load()
        profile["character"] = {"name": "Clara", "preset_id": "clara_moreau"}
        assert st.save(profile) is None  # pas d'erreur
        again = RelationState(str(tmp_path), "abc123").load()
        assert again["character"]["name"] == "Clara"

    def test_set_score_marque_interaction(self, tmp_path):
        st = RelationState(str(tmp_path), "abc123")
        profile = st.load()
        st.set_score(profile, 450)
        assert profile["relationship_score"] == 450
        assert profile["relationship_stage"] == "neutre"
        assert profile["interaction_count"] == 1
        assert profile["last_interaction"]

    def test_set_score_sans_marque(self, tmp_path):
        st = RelationState(str(tmp_path), "abc123")
        profile = st.load()
        st.set_score(profile, 300, mark_interaction=False)
        assert profile["interaction_count"] == 0
        assert not profile["last_interaction"]

    def test_add_photo_dedoublonne(self, tmp_path):
        st = RelationState(str(tmp_path), "abc123")
        profile = st.load()
        st.add_photo(profile, "portrait.png", "portrait", "Photo de profil")
        st.add_photo(profile, "portrait.png", "portrait", "Photo de profil")
        assert len(profile["photos"]) == 1
        st.add_photo(profile, "photo_x.png", "photo", "Souvenir")
        assert len(profile["photos"]) == 2
        assert st.photo_url("portrait.png") == "/data/photos/abc123/portrait.png"

    def test_delete(self, tmp_path):
        st = RelationState(str(tmp_path), "abc123")
        profile = st.load()
        profile["character"] = {"name": "X"}
        st.save(profile)
        (tmp_path / f"chat_abc123.json").write_text("[]", encoding="utf-8")
        st.delete()
        fresh = RelationState(str(tmp_path), "abc123").load()
        # Après suppression : profil neuf (identité conservée, données vides).
        assert fresh["meta"]["session_id"] == "abc123"
        assert fresh["character"] == {}
        assert fresh["relationship_score"] == 100

    def test_session_inexistante_profil_neuf(self, tmp_path):
        st = RelationState(str(tmp_path), "zzzz")
        profile = st.load()
        assert "_erreur" not in profile
        assert profile["relationship_score"] == 100
        assert profile["meta"]["session_id"] == "zzzz"
