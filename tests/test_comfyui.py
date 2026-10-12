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


class TestMappingUsage:
    def test_les_deux_usages_pointent_vers_qwen_21(self, tmp_path):
        # portrait et photo partagent le graphe de génération Qwen 2.1.
        wf = {"2": {"class_type": "KSampler", "inputs": {"seed": 0}}}
        (tmp_path / "image_qwen_image_2_1_api.json").write_text(
            json.dumps(wf), encoding="utf-8"
        )
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        b._workflows_dir = str(tmp_path)
        assert b._load_workflow("portrait") == wf
        assert b._load_workflow("photo") == wf

    def test_repli_sur_usage_json_si_absent(self, tmp_path):
        # Sans fichier mappé, la convention historique reste honorée.
        wf = {"2": {"class_type": "KSampler", "inputs": {"seed": 0}}}
        (tmp_path / "portrait.json").write_text(json.dumps(wf), encoding="utf-8")
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        b._workflows_dir = str(tmp_path)
        assert b._load_workflow("portrait") == wf


class TestPatchQwenImage21:
    def test_prompt_injecte_dans_textencodeqwenimage21(self):
        # Le nœud Qwen Image 2.1 expose la clé `prompt` (et non `text`).
        wf = {
            "459:452": {"class_type": "TextEncodeQwenImage21",
                        "inputs": {"prompt": "Image prompt.", "negative_prompt": ""}},
            "459:458": {"class_type": "KSampler", "inputs": {"seed": 1}},
        }
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        graph, seed = b._patch_workflow(wf, "un portrait", "portrait", 7)
        assert graph["459:452"]["inputs"]["prompt"] == "un portrait"
        assert graph["459:458"]["inputs"]["seed"] == 7
        assert seed == 7
        # copie profonde : le graphe source n'est pas muté
        assert wf["459:452"]["inputs"]["prompt"] == "Image prompt."

    def test_textgenerate_non_confondu_avec_encodeur(self):
        # Le workflow d'édition contient un nœud TextGenerate (autre modèle) :
        # le prompt doit viser l'encodeur d'image, pas le générateur de texte.
        wf = {
            "459:500": {"class_type": "TextGenerate",
                        "inputs": {"prompt": "Image Prompt", "max_length": 4096}},
            "459:474": {"class_type": "TextEncodeQwenImage21",
                        "inputs": {"prompt": ["459:480", 0], "negative_prompt": ""}},
            "459:458": {"class_type": "KSampler", "inputs": {"seed": 1}},
        }
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        graph, _ = b._patch_workflow(wf, "scene", "photo", 5)
        assert graph["459:474"]["inputs"]["prompt"] == "scene"
        assert graph["459:500"]["inputs"]["prompt"] == "Image Prompt"

    def test_sampler_prioritaire_pour_la_seed(self):
        # Un nœud annexe exposant `seed` ne doit pas voler la seed au sampler.
        wf = {
            "459:452": {"class_type": "TextEncodeQwenImage21",
                        "inputs": {"prompt": "x"}},
            "459:500": {"class_type": "TextGenerate",
                        "inputs": {"prompt": "y", "seed": 999}},
            "459:458": {"class_type": "KSampler", "inputs": {"seed": 1}},
        }
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        graph, _ = b._patch_workflow(wf, "p", "photo", 33)
        assert graph["459:458"]["inputs"]["seed"] == 33
        assert graph["459:500"]["inputs"]["seed"] == 999

    def test_workflow_reel_qwen_patche(self):
        # Bout en bout sur le fichier réellement livré : le prompt et la seed
        # atterrissent dans les bons nœuds du graphe Qwen Image 2.1 Turbo.
        b = ComfyUIBackend(base_url="http://127.0.0.1:9")
        graph, seed = b._patch_workflow(
            b._load_workflow("portrait"), "hello portrait", "portrait", 123,
        )
        assert any(
            v.get("class_type") == "TextEncodeQwenImage21"
            and v.get("inputs", {}).get("prompt") == "hello portrait"
            for v in graph.values()
        )
        assert graph["459:458"]["inputs"]["seed"] == 123
        assert seed == 123

