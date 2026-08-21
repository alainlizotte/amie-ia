# Tests du backend ComfyUI — chargement des workflows JSON.

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.image.comfyui import ComfyUIBackend  # noqa: E402


class TestChargementWorkflow:
    def test_charge_workflow_sans_bom(self, tmp_path):
        wf = {"1": {"class_type": "KSampler", "inputs": {"seed": 0}}}
        (tmp_path / "portrait.json").write_text(
            json.dumps(wf), encoding="utf-8"
        )
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        b._workflows_dir = str(tmp_path)
        assert b._load_workflow("portrait") == wf

    def test_tolere_bom_utf8(self, tmp_path):
        # Les éditeurs Windows ajoutent parfois un BOM : le chargement
        # ne doit pas échouer (bug réel rencontré en conteneur).
        wf = {"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}
        (tmp_path / "portrait.json").write_bytes(
            b"\xef\xbb\xbf" + json.dumps(wf).encode("utf-8")
        )
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        b._workflows_dir = str(tmp_path)
        assert b._load_workflow("portrait") == wf

    def test_fichier_absent_leve_erreur(self, tmp_path):
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        b._workflows_dir = str(tmp_path)
        try:
            b._load_workflow("portrait")
            raise AssertionError("ComfyUIError attendu")
        except Exception as e:
            from server.image.comfyui import ComfyUIError
            assert isinstance(e, ComfyUIError)

    def test_patch_prompt_et_seed(self, tmp_path):
        wf = {
            "108_PROMPT_NODE": {"class_type": "CLIPTextEncode",
                                "inputs": {"text": "original"}},
            "106_SEED_NODE": {"class_type": "KSampler",
                              "inputs": {"seed": 0}},
        }
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        graph, seed = b._patch_workflow(wf, "nouveau prompt", "portrait", 42)
        assert graph["108_PROMPT_NODE"]["inputs"]["text"] == "nouveau prompt"
        assert graph["106_SEED_NODE"]["inputs"]["seed"] == 42
        assert seed == 42
