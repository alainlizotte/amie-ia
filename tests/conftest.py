# conftest.py — isolé AVANT tout import de server.* : redirige la config et
# les données vers un dossier temporaire, désactive backends externes.

import os
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="amie_tests_"))
(_TEST_ROOT / "config").mkdir(parents=True, exist_ok=True)

_CONFIG_PATH = _TEST_ROOT / "config" / "config.yaml"
_DATA_DIR = _TEST_ROOT / "data"

# Config de test : données isolées, LLM/embeddings/ComfyUI désactivés ou
# injoignables (aucun réseau sortant nécessaire pour la suite).
_CONFIG_PATH.write_text(
    f"""
llm:
  backend: llamacpp
  base_url: http://127.0.0.1:9/v1
  model: test-model
memory:
  enabled: false
  embedding_base_url: http://127.0.0.1:9/v1
image:
  enabled: false
paths:
  data_dir: {_DATA_DIR.as_posix()}
""",
    encoding="utf-8",
)

os.environ["AMIE_CONFIG"] = str(_CONFIG_PATH)
os.environ.pop("COMFYUI_BASE_URL", None)
