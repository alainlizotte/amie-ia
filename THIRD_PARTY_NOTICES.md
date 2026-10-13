# 🧾 Licences tierces

Le code de ce dépôt est distribué sous licence [MIT](LICENSE).

**Les modèles d'IA ne sont pas inclus** (trop volumineux) et **aucune image
générée n'est versionnée** : chaque personne télécharge elle-même les modèles
sur Hugging Face et est responsable de la licence qui s'y applique. Le tableau
ci-dessous résume ces licences à titre d'information.

## ⚖️ Avertissement légal (à lire avant d'activer la génération d'images)

Si vous activez la génération d'images, **c'est vous qui téléchargez les
modèles et acceptez leurs licences**. Choisissez de préférence un modèle sous
**licence permissive** (Apache 2.0) : un modèle « recherche uniquement » n'est
**pas** adapté à un jeu de divertissement — même gratuit, même open source,
même en local et même sans redistribuer les images, son usage sort du champ de
sa licence.

> Ce document est fourni à titre informatif et **ne constitue pas un avis
> juridique**. Pour un enjeu réel, consultez un professionnel du droit.

## Modèles d'IA (téléchargés par l'utilisateur)

| Modèle | Rôle | Licence | Usage pour ce jeu |
|---|---|---|---|
| [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) et fine-tune [HauhauCS Uncensored](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive) (GGUF + mmproj) | Chat + vision | Apache 2.0 | ✅ Libre |
| **[Qwen-Image (1.0)](https://huggingface.co/Qwen/Qwen-Image)** | **Génération d'images (ComfyUI) — recommandé** | **Apache 2.0** | ✅ **Libre** |
| **[FLUX.1 [schnell]](https://huggingface.co/black-forest-labs/FLUX.1-schnell)** | **Génération d'images (ComfyUI) — alternative recommandée** | **Apache 2.0** | ✅ **Libre** |
| [Qwen-Image-2.1-Turbo](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo) | Génération d'images (déconseillé) | Qwen Research License | ❌ Hors champ (recherche/évaluation uniquement) |
| embeddinggemma-300M-qat (GGUF) | Embeddings (mémoire) | Gemma Terms of Use | ✅ Usage commercial autorisé, sous conditions |
| nomic-embed-text-v1.5 (GGUF) | Embeddings (alternatif) | Apache 2.0 | ✅ Libre |

## Génération d'images — recommandations

La génération d'images est **optionnelle** : elle délègue à un serveur
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) installé séparément par
l'hébergeur. Aucun modèle n'est embarqué dans ce dépôt, et **aucune image
générée n'est versionnée**.

### ✅ Modèles recommandés (licence permissive)

- **[Qwen-Image (1.0)](https://huggingface.co/Qwen/Qwen-Image)** — Apache 2.0,
  même écosystème ComfyUI (fichiers repackagés
  [Comfy-Org](https://huggingface.co/Comfy-Org)) ;
- **[FLUX.1 [schnell]](https://huggingface.co/black-forest-labs/FLUX.1-schnell)**
  — Apache 2.0 ;
- **[Stable Diffusion 3.5](https://huggingface.co/stabilityai/stable-diffusion-3.5-medium)**
  — Stability Community License (usage commercial gratuit < 1 M$ de revenus).

Le workflow ComfyUI fourni avec le dépôt référence un autre modèle (voir
ci-dessous) : **adaptez-le** au modèle permissif choisi (mêmes nœuds de base,
autres poids).

### ⚠️ Qwen-Image-2.1-Turbo — pourquoi il n'est plus recommandé

Qwen-Image-2.1-Turbo est distribué sous la [Qwen RESEARCH LICENSE
AGREEMENT](QWEN_RESEARCH_LICENSE.txt) (20 septembre 2026), qui n'accorde les
droits d'usage que **« FOR NON-COMMERCIAL PURPOSES ONLY »**, « non-commercial »
étant défini exclusivement comme *« research or evaluation purposes only »*
(§1i).

Un jeu de divertissement n'entre dans aucun de ces champs. **Générer des images
pour ce jeu — prédéfinies ou à la volée — est hors du périmètre de la licence**,
même si le projet est gratuit et open source, même en local, et même si les
images ne sont pas redistribuées. Le fait de détenir les images produites ne
rend pas l'usage du modèle conforme : la licence porte sur **l'usage du
modèle** (§2), pas sur la propriété des sorties.

Le workflow livré (`server/image/workflows/image_qwen_image_2_1_api.json`) est
conservé pour compatibilité mais **n'est pas recommandé**.

Usage commercial de Qwen-Image-2.1 : demander une licence à
`model-business@notice.qwencloud.com` (§2b de la licence).

### Obligations en cas de redistribution des Materials Qwen (§3)

Si vous redistribuez les poids Qwen (ou des fichiers dérivés), la licence exige
(§3a–c) : joindre une copie de l'accord, signaler les fichiers modifiés et
conserver l'attribution :

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
