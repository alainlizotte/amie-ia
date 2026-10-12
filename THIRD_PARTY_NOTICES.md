# 🧾 Licences tierces

Le code de ce dépôt est distribué sous licence [MIT](LICENSE).

**Les modèles d'IA ne sont pas inclus dans ce dépôt** (trop volumineux) :
chaque personne les télécharge séparément sur Hugging Face et est
responsable de la licence qui s'y applique. Le tableau ci-dessous résume ces
licences à titre d'information.

## Modèles d'IA (téléchargés par l'utilisateur)

| Modèle | Rôle | Licence | Usage pour ce jeu |
|---|---|---|---|
| [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) et fine-tune [HauhauCS Uncensored](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive) (GGUF + mmproj) | Chat + vision | Apache 2.0 | ✅ Libre |
| [Qwen-Image-2.1-Turbo](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo) (+ encodeur texte qwen3vl, VAE) | Génération d'images (ComfyUI) | Qwen Research License | ⚠️ Recherche/évaluation uniquement |
| embeddinggemma-300M-qat (GGUF) | Embeddings (mémoire) | Gemma Terms of Use | ✅ Usage commercial autorisé, sous conditions |
| nomic-embed-text-v1.5 (GGUF) | Embeddings (alternatif) | Apache 2.0 | ✅ Libre |

## ⚠️ Qwen-Image-2.1-Turbo — licence « recherche uniquement »

Qwen-Image-2.1-Turbo est distribué sous la [Qwen RESEARCH LICENSE
AGREEMENT](QWEN_RESEARCH_LICENSE.txt) (20 septembre 2026), qui n'accorde les
droits d'usage que **« FOR NON-COMMERCIAL PURPOSES ONLY »**, « non-commercial »
étant défini exclusivement comme *« research or evaluation purposes only »*
(§1i).

**Transparence** : un jeu comme Ami(e) IA n'entre pas dans ce champ. L'utiliser
pour générer des images de divertissement — portraits prédéfinis, photos du
jeu — n'est ni de la recherche ni de l'évaluation, même lorsque le projet est
gratuit et open source. Les portraits prédéfinis versionnés dans
`server/data/preset_portraits/` ont d'ailleurs été générés avec ce modèle :
cet usage était hors du champ de la licence.

Chaque personne qui télécharge et utilise ce modèle accepte la licence et en
assume la conformité. Pour rester pleinement en règle, privilégier un modèle
d'image sous licence permissive :

- **[Qwen-Image (1.0)](https://huggingface.co/Qwen/Qwen-Image)** — Apache 2.0,
  même écosystème ComfyUI (fichiers repackagés [Comfy-Org](https://huggingface.co/Comfy-Org)) ;
- **[FLUX.1 [schnell]](https://huggingface.co/black-forest-labs/FLUX.1-schnell)** — Apache 2.0 ;
- **[Stable Diffusion 3.5](https://huggingface.co/stabilityai/stable-diffusion-3.5-medium)** —
  Stability Community License (usage commercial gratuit < 1 M$ de revenus).

Usage commercial de Qwen-Image-2.1 : demander une licence à
`model-business@notice.qwencloud.com` (§2b de la licence).

En cas de redistribution des Materials Qwen (poids, fichiers dérivés), la
licence exige (§3a–c) : joindre une copie de l'accord, signaler les fichiers
modifiés et conserver l'attribution :

> Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT,
> Copyright (c) 2026 Hangzhou Tongyi Laboratory Technology Co., Ltd.
> All Rights Reserved.

## Logiciels tiers exécutés ou référencés

| Composant | Rôle | Licence |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Serveur LLM / embeddings (Docker) | MIT |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | Génération d'images (service externe, non redistribué) | GPL-3.0 |
| [FastAPI](https://github.com/fastapi/fastapi) | Serveur web (Python) | MIT |
| [uvicorn](https://github.com/Kludex/uvicorn) | Serveur ASGI | BSD-3-Clause |
| [httpx](https://github.com/encode/httpx) | Client HTTP | BSD-3-Clause |
| [pydantic](https://github.com/pydantic/pydantic) | Validation | MIT |
| [PyYAML](https://github.com/yaml/pyyaml) | Configuration YAML | MIT |
| [websockets](https://github.com/python-websockets/websockets) | WebSocket | BSD-3-Clause |
| [pytest](https://github.com/pytest-dev/pytest) / [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | Tests | MIT / Apache 2.0 |
| [React](https://github.com/facebook/react), [Vite](https://github.com/vitejs/vite), [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) | Client web | MIT |
| [TypeScript](https://github.com/microsoft/TypeScript) | Client web | Apache 2.0 |
