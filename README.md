# 💕 Ami(e) IA — Rencontres virtuelles

> **⚠️ Contenu pour adultes averti (18 ans +)** — Cette application simule des
> relations virtuelles et peut générer des contenus sensibles à mesure que la
> relation évolue. Une déclaration de majorité est demandée à la connexion.

Application de **simulation d'application de rencontre** avec des personnages
IA : vous avez *matché* avec un personnage et vous discutez dans le
clavardage de l'app, comme sur Tinder. Vos mots font évoluer la relation, et
vous découvrez peu à peu son histoire — jusqu'à décrocher des photos et
atteindre une relation « proche ».

Le personnage est **conscient en tout temps** qu'il discute sur une
application de rencontre : c'est un match, avec une vie de son côté de
l'écran (travail, amis, loisirs). Il agit comme une vraie personne et se
tient à son rôle défini — jamais un assistant.

Le tout tourne **en local sur votre machine** (aucune donnée envoyée sur
Internet) : chat sous llama.cpp (Qwen 3.5), images sous ComfyUI
(**Qwen-Image 1.0** ou **FLUX.1 [schnell]** — modèles sous licence permissive
Apache 2.0 ; voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)),
mémoire vectorielle sous un serveur d'embeddings.

---

## 🎯 Le but du jeu

Chaque rencontre démarre au stade **« froid »** (score 100/1000) — deux
personnes qui viennent de matcher et n'ont jamais discuté :

```
rejet → froid → réservé → neutre → chaleureux → proche
```

- **Discutez** avec le personnage : chaque message est analysé par un moteur
  déterministe qui ajuste le score relationnel (+/- points selon la
  gentillesse, l'intérêt porté, les impairs…).
- **Faites monter la relation** : franchir un stade débloque de nouveaux
  scénarios narratifs et le droit de demander des 📷 **photos**
  (refusées avant le stade « neutre »).
- **Vivez les scénarios** : le serveur injecte périodiquement des événements
  scriptés (rendez-vous, surprises, crises…) selon votre stade — au total
  **275 scénarios** répartis sur les personnages.
- **Entretenez le lien** : après 3 jours sans nouvelles, la relation se
  dégrade (-10 pts/jour). Les absents sont punis !
- **Objectif** : atteindre le stade « proche »… et y rester.

## ✨ Fonctionnalités

| | |
|---|---|
| 💬 **Chat en temps réel** | WebSocket, réponses streaming du personnage, indicateur de saisie |
| 🎭 **25 personnages** | Personnages prédéfinis (apparence, caractère, histoire) ou création personnalisée — portraits **générés localement à la première session** (aucune image pré-générée n'est versionnée dans le dépôt) et servis en **vignette dans le sélecteur** |
| ❤️ **Relation chiffrée** | Score /1000 + stades affichés, évolution visible après chaque message |
| 📸 **Album photo** | Portrait généré automatiquement à la rencontre ; photos qui reflètent la scène en cours (le « directeur photo » analyse les derniers échanges) — cadrage **selfie** par défaut (téléphone tenu dans sa main), sauf demande contraire. Image ratée ? bouton **🔄 Régénérer** dans l'album : même scène, nouvelle seed |
| 💌 **Messages proactifs** | Après 24 h de silence, le personnage vous écrit ; relances espacées de façon croissante puis plafonnées (max 6, dont un adieu), **-15 points** par relance ignorée — badge rouge avec compteur sur son encadré dans *Mes rencontres*. Le ton monte avec le silence sans jamais régresser : ennui → inquiétude → tristesse → frustration → colère blessée |
| 💞 **Rendez-vous interactifs** | Le « réalisateur invisible » : le personnage propose une activité en texto (film synchronisé à froid → escapade à proche, 2 scénarios par stade), votre réponse fait avancer la scène — acceptation, refus, choix implicites — et une **photo souvenir à deux** (votre photo + le personnage, en mode édition ComfyUI) ponctue les rencontres en vrai. 100 % conversation, aucune interface dédiée |
| 🎮 **Jeu de l'app** | « Deux vérités, un mensonge » présenté comme une fonctionnalité de l'application (carte d'annonce) : le personnage joue comme un humain, vous devinez, puis la **manche 2** inverse les rôles — à vous de piéger |
| 🤳 **Initiative photo** | Le personnage peut envoyer de lui-même des photos pertinentes (stade Neutre+) |
| 🎲 **Mini-jeux** | Trois jeux de conversation lancés d'un bouton — « Deux vérités, un mensonge », « Action ou vérité », « 20 questions » — questions liées au personnage et filtrées par stade, issue vérifiée côté serveur, points de relation à la clé |
| 🔒 **Garde-fous techniques** | Tenue des photos contrainte par stade côté serveur — le LLM ne peut pas contourner : sobre à « neutre », « jamais nue » à « chaleureux », **« jamais nue » à « proche » par défaut** (nudité explicite activable via `image.allow_explicit_from_proche: true`) |
| 🧠 **Mémoire** | Extraction périodique de souvenirs + rappel sémantique (le personnage se souvient de vous) |
| 👤 **Mon profil** | Votre propre fiche « dating app » (mêmes catégories que les personnages) + photo analysée par le modèle **vision** — le personnage sait avec qui il parle et s'y réfère naturellement |
| 👤 **Comptes locaux** | Inscription/connexion avec tokens Bearer — chaque utilisateur voit uniquement ses sessions |
| 🔔 **Notifications OS** | Alertes système quand ton match écrit pendant que l'app est en arrière-plan — désactivable dans « Mon profil » |
| 🔊 **Voix des messages** | Lecture vocale automatique (Web Speech API, voix du système, locale) avec un profil vocal par personnage — genre + personnalité → pitch/vitesse ; bouton 🔊 pour réécouter. Désactivable dans « Mon profil » |
| 🖼 **Visionneuse** | Album consultable plein écran (clavier ←/→, Échap) |
| 📱 **Mobile** | Panneau d'informations accessible en superposition via le bouton ⓘ |

## ⚙️ Comment ça marche

La particularité d'Ami(e) IA : la mécanique de jeu est **100 % déterministe
et côté serveur**. Le LLM n'incarne QUE le personnage — il ne calcule ni
score, ni stades, ni scénarios, ni photos. Impossible de le convaincre de
« tricher ».

```
client/          React 18 + TS + Vite 6 + Tailwind v4 (build → server/static)
server/
  main.py        FastAPI : REST + WebSocket chat + statique + messages proactifs
  auth.py        Comptes PBKDF2 + tokens Bearer HMAC
  config.py      Chargement YAML (config/config.yaml)
  relation/      Score, stades, scénarios, presets, souvenirs (déterministe)
  llm/           Client llama.cpp (streaming SSE, vision) + prompt builder
  user_profile.py  Fiche « dating app » de l'utilisateur (injectée au prompt)
  image/         ComfyUI : portrait auto + photos gated par stade
  prompts/       Persona du personnage (SystemPrompt_Compagnon.md)
data/
  character_presets/   25 personnages + 275 scénarios (portés de l'original)
server/data/     Runtime : sessions, historiques, photos, utilisateurs.json
                 + preset_portraits/ (cache local des portraits — NON versionné)
config/          config.yaml (local, gitigné) — voir config.example.yaml
```

### Mécanique détaillée

- **Score relationnel** (100 au départ) ajusté après chaque message par un
  moteur mots-clés/patterns ; stades : rejet → froid → réservé → neutre →
  chaleureux → proche. Barème de base (`server/relation/scoring.py`),
  multiplié par `relation.gain_multiplier` (1.5 par défaut — **tout le
  barème +50 %**, gains et malus) :

  | Signal | Base | Effectif (×1.5) |
  |---|---|---|
  | Message neutre (aucun signal détecté) | **+1** (plancher garanti — discuter fait toujours progresser) | +2 |
  | Politesse neutre (salut, ça va…) | +3 | +5 |
  | Engagement (message > 200 caractères) | +3 | +5 |
  | Compliment / remerciement (par mot-clé) | +6 | +9 |
  | Excuses sincères | +6 | +9 |
  | « tu es + [adjectif positif] » | +8 (1× par message) | +12 |
  | Insistance inappropriée à un stade bas | -6 | -9 |
  | Insulte non dirigée | -10 | -15 |
  | Insulte dirigée (« tu es… », « sale… ») | -16 | -24 |

  L'appariement des mots-clés est insensible aux accents (« genial » vaut
  « génial »). Delta borné à [delta_min ; delta_max] ([-30 ; +24] par
  défaut — élargir ces bornes proportionnellement au multiplicateur).
  Logique négative préservée quel que soit le multiplicateur : un message
  contenant un malus n'est jamais rattrapé par le plancher, et une insulte
  (-24) pèse toujours plus qu'un compliment simultané (+9).

- **Scénarios** (lettres A-K par personnage) injectés côté serveur selon les
  gates de stade ; consommation détectée par similarité cosinus entre le
  scénario et la réponse (embeddings), forcée après 3 tours.
- **Décroissance temporelle** après 3 jours d'absence (-10 pts/jour,
  plafond -150).
- **Persona « dating app »** : le prompt système ancre le personnage dans le
  contexte de l'application de rencontre en tout temps — il sait qu'il parle
  à un match, connaît les codes de l'app, vit sa propre vie hors clavardage
  et ne connaît de vous que la conversation et votre profil. Il ne rompt
  jamais son rôle : pas de référence à l'IA, au système ou aux mécaniques
  de jeu.
- **Mon profil (utilisateur)** : remplissez votre fiche via le bouton
  « 👤 Mon profil » — mêmes catégories que les personnages (prénom, âge,
  apparence, personnalité, métier, intérêts, histoire, situation amoureuse,
  recherches). Elle est injectée dans chaque prompt : le personnage connaît
  son match. Photo optionnelle : uploadée en base64, analysée par le modèle
  vision Qwen (mmproj chargé par llama.cpp), et la description générée
  complète la fiche (saisie manuelle possible si le modèle n'a pas de
  vision).
- **Souvenirs** : extraction périodique (tous les 10 tours) + rappel
  sémantique top-k.
- **Photos** : portrait généré automatiquement à la création de session ;
  demandes via bouton 📷 (refusées avant le stade « neutre »). Le prompt est
  construit par un « directeur photo » : un appel LLM court résume les
  derniers échanges en fragments visuels (lieu, pose, regard), sanitisés
  selon le stade. Cadrage par défaut : **selfie** (téléphone tenu dans sa
  main, bras tendu), sauf avis contraire exprimé dans la conversation.
  **Nudité explicite : désactivée par défaut** (plafond « jamais nue », stade
  « proche » compris). Elle peut être activée via
  `image.allow_explicit_from_proche: true` — dans ce cas seulement, une
  demande explicite de photo nue est acceptée à partir du stade « proche »
  (jamais d'explicite avant « proche », quelle que soit la demande).
- **Messages proactifs** : après 24 h sans échange, le personnage écrit le
  premier (jamais au stade « rejet »). Les relances sont **espacées de façon
  croissante** (24 h, puis ×2, ×3…) et **plafonnées** : après 6 messages sans
  réponse (1 ouverture + 5 niveaux de gradation), le dernier est un adieu et
  le personnage cesse d'écrire tant que vous n'avez pas répondu. Si une
  relance fait basculer la relation au stade « rejet » (**-15 points** par
  relance ignorée), un unique adieu froid est envoyé, puis silence total. La
  gradation émotionnelle (ennui → inquiétude → tristesse → frustration →
  colère blessée) est imposée par le serveur : elle ne régresse pas, la
  durée du silence citée est contrôlée, et le personnage ne vous prête
  jamais de réponse imaginaire. Un badge rouge avec le nombre de messages
  sans réponse s'affiche sur l'encadré du personnage dans « Mes rencontres » ;
  il disparaît dès que vous répondez (et rouvre le cycle pour un prochain
  silence).
- **Initiative photo** : au stade Neutre+, le personnage peut envoyer de
  lui-même une photo (probabilité par tour, plus élevée avec un message
  spontané) — même pipeline directeur photo + garde-fous de tenue.
- **Mini-jeux** (bouton 🎲 du chat) : l'état, les contenus et l'issue sont
  100 % déterministes (`server/relation/games.py`) — le LLM n'incarne que le
  personnage autour des contenus choisis par le serveur ; les questions sont
  **liées au personnage** (intérêts, métier, âge) et **filtrées par stade**.
  « Deux vérités, un mensonge » est présenté comme un **jeu de
  l'application** (carte d'annonce 🎮, comme les icebreakers Bumble/Hinge) :
  le personnage y joue comme un humain, jamais comme un bot — et la
  **manche 2** inverse les rôles (vous piégez, il/elle devine) :
  - **Deux vérités, un mensonge** (dès « froid ») : 3 énoncés bâtis sur la
    fiche visible du personnage (2 vrais + 1 faux) ; le match devine « 1 »,
    « 2 » ou « 3 » — attention récompensée (+12 gagné, +4 perdu, ×
    multiplicateur), le mensonge est ensuite révélé.
  - **Action ou vérité** (dès « réservé ») : après le choix du match, le
    serveur tire la vérité ou le défi dans des banques graduées par stade
    (brise-glace à « froid » → audacieux à « proche ») et colorées par les
    intérêts du personnage ; répondre rapporte +6.
  - **20 questions** (dès « froid ») : un objet secret lié à l'univers du
    personnage (escalade → une raquette, lecture → un livre…) ; chaque
    question oui/non fait avancer le compteur, des indices tombent aux
    questions 5/10/15 ; trouvé en ≤ 20 questions : +14, sinon +4. La
    victoire est vérifiée par mots-clés côté serveur (insensible aux
    accents, message court requis).
  Un jeu s'éteint après 3 messages hors-jeu, au stade « rejet », ou sur un
  « j'abandonne » ; il est suspendu pendant un rendez-vous. Le client
  affiche des réponses rapides (puces) selon l'état ; l'état public ne
  contient JAMAIS le mensonge ni l'objet secret.
- **Rendez-vous interactifs** (`server/relation/dates.py`) — le
  « réalisateur invisible » : aucune interface dédiée, tout se joue dans la
  conversation. Le serveur propose (cooldown 48 h, ≥ 3 échanges, gates par
  stade) ; votre réponse est classée déterministement : **acceptée** (les
  étapes se déroulent, une par tour), **refusée** (dignité, aucune
  pression) ou **évasive** (une relance douce, puis laisser-aller). Les
  étapes à « moment clé » offrent des choix implicites détectés par
  mots-clés (terrasse ou intérieur ? fromages ou douceurs ?…) avec une
  scène dédiée par choix. Scénarios par stade (2 chacun) :
  - **froid / réservé** : activités à distance crédibles entre inconnus —
    film synchronisé, playlist, défi cuisine à distance, balade commentée
    (jamais de rencontre physique avant « neutre », conforme aux consignes
    de stade) ;
  - **neutre** : première vraie rencontre (premier café, marché du
    samedi) ;
  - **chaleureux** : souper cuisiné à deux, soirée arcade ;
  - **proche** : escapade d'une journée, soirée cocooning.
  À la conclusion : +10 points, le souvenir est rangé en mémoire (« notre
  premier café ») et une **photo souvenir** est générée — en mode ÉDITION
  ComfyUI : votre photo de profil sert de canevas (identité préservée par
  le modèle d'édition) et le personnage est ajouté à vos côtés dans la
  scène ; replis en cascade (échec d'édition ou pas de photo joueur →
  photo solo ; garde-fous de tenue par stade inchangés).
- **VRAM** : le modèle de chat est déchargé quand aucun tour n'est actif
  (immédiat ou après un délai configurable), et **systématiquement déchargé
  avant chaque génération d'image puis rechargé une fois la génération
  terminée** — ComfyUI (le modèle d'image configuré) dispose ainsi toujours de la
  place nécessaire, même lorsque le modèle de chat reste chargé entre les
  tours.
- **18+** : mention affichée sur l'écran de connexion + case de déclaration
  de majorité obligatoire.

## 🚀 Installation & démarrage (Docker, recommandé)

Prérequis :
- **Docker Desktop** avec support GPU NVIDIA (recommandé ; sans GPU, voir la
  note dans `docker-compose.yml` pour passer en CPU) ;
- les **modèles GGUF** téléchargés (voir « 🧠 Modèles » ci-dessous) ;
- *(optionnel)* **ComfyUI** sur l'hôte (port 8188) pour les images — utile
  pour générer les portraits des personnages prédéfinis (plus inclus au dépôt).

```powershell
git clone https://github.com/alainlizotte/amie-ia.git
cd "amie-ia"
copy config.example.yaml config\config.yaml
.\scripts\demarrer-serveur.bat     # docker compose up -d --build
# → http://localhost:8124
.\scripts\arreter-serveur.bat      # arrêt
```

Le docker-compose lance **tout le nécessaire** : le serveur web Ami(e) IA,
llama.cpp (chat, GPU) et le serveur d'embeddings (mémoire sémantique, CPU).
Aucune autre application n'est requise.

Ports : web **8124**, llama.cpp **8082**, embeddings **8083** (choisis pour
coexister avec un éventuel autre projet llama.cpp sur 8080/8081).

## 🛠 Développement local

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn server.main:app --port 8000

cd client
npm install
npm run dev          # http://localhost:5174 (proxy /api /ws /data → 8000)
npm run build        # → ../server/static
```

En local, adapter `config/config.yaml` :
`llm.base_url: http://127.0.0.1:8082/v1` et
`memory.embedding_base_url: http://127.0.0.1:8083/v1`
(ou lancer les serveurs llama.cpp vous-même sur les ports de votre choix).

## Configuration

Copier `config.example.yaml` vers `config/config.yaml` puis ajuster :
backend LLM (`llamacpp`/`ollama`), modèle, streaming vers les clients
(`stream_to_clients`), déchargement VRAM (`unload_after_turn`),
paramètres relationnels (cooldown des scénarios, décroissance, seuils de
similarité…).

## 🧠 Modèles

Deux modèles GGUF sont requis (non versionnés : trop volumineux).
Téléchargez-les sur Hugging Face et placez-les aux emplacements indiqués :

| Rôle | Modèle | Emplacement | Taille |
|---|---|---|---|
| Chat (défaut) | [Qwen3.5-9B-Uncensored-HauhauCS-Aggressive](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive), quant **Q4_K_M** | `models/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M/` | ~5,6 Go (+ mmproj ~0,9 Go) |
| Embeddings (mémoire) | `embeddinggemma-300M-qat-Q4_0.gguf` | `models-embed/` | ~265 Mo |

- `llm.model` dans `config/config.yaml` doit correspondre à l'identifiant du
  modèle tel que listé par `GET /v1/models` du serveur llama.cpp (par défaut
  le nom du sous-dossier de `models/`) — c'est déjà le cas dans
  `config.example.yaml`.
- **Qwen 3.5** : le thinking est désactivé côté client via
  `chat_template_kwargs {enable_thinking: false}` (`llm.think: false`),
  les messages sont normalisés pour la template stricte (system uniquement
  en tête) et les blocs `<think>…</think>` éventuels sont filtrés des
  réponses, en direct comme en streaming.
- **Autres modèles** : Gemma 4, Mistral, etc. restent utilisables — changer
  `llm.model` (et le dossier sous `models/`) ; le strip thinking Gemma
  (`<|channel>thought…<channel|>`) est également géré.

### 🧾 Licences des modèles

Les modèles ne sont pas redistribués par ce dépôt : chacun les télécharge sur
Hugging Face et est responsable de la licence qui s'y applique — détail
complet dans [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- **Qwen3.5-9B** et son fine-tune **HauhauCS Uncensored** : Apache 2.0 —
  usage libre, y compris pour ce jeu.
- **embeddinggemma-300M** : Gemma Terms of Use (usage commercial autorisé) ;
  **nomic-embed-text-v1.5** : Apache 2.0.
- ✅ **Génération d'images : Qwen-Image (1.0)** ou **FLUX.1 [schnell]** —
  Apache 2.0, usage libre (**recommandé**).
- ❌ **Qwen-Image-2.1-Turbo n'est plus recommandé** : Qwen RESEARCH LICENSE
  AGREEMENT — **recherche/évaluation uniquement**. L'utiliser pour générer des
  images de jeu (divertissement) est **hors du champ de la licence**, même
  gratuitement, même en open source, même en local et même sans redistribuer
  les images. Ce dépôt ne distribue ni le modèle ni ses sorties.

### Modèles d'images (ComfyUI)

La génération d'images est **optionnelle** et délègue à un serveur
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) installé séparément.
**Modèle recommandé : [Qwen-Image (1.0)](https://huggingface.co/Qwen/Qwen-Image)
ou [FLUX.1 [schnell]](https://huggingface.co/black-forest-labs/FLUX.1-schnell)
— Apache 2.0** (usage libre, y compris pour ce jeu). Adaptez le workflow
ComfyUI au modèle choisi (mêmes nœuds de base, autres poids).

> ⚠️ **Le workflow livré** (`server/image/workflows/image_qwen_image_2_1_api.json`)
> référence **Qwen-Image-2.1-Turbo**, sous la Qwen RESEARCH LICENSE AGREEMENT
> (**recherche/évaluation uniquement**, donc inadapté à un jeu). Il est
> conservé pour compatibilité mais **n'est plus recommandé** — voir
> [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Avant chaque génération, le modèle de chat est déchargé de la VRAM puis
rechargé à la fin (voir `server/gpu.py`).

## API

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/health` | État des backends |
| POST | `/api/auth/inscription` | Création de compte → `{token, utilisateur}` |
| POST | `/api/auth/connexion` | Connexion → token Bearer (30 jours) |
| GET | `/api/auth/moi` | Identité du porteur du token |
| GET | `/api/presets` | Personnages prédéfinis |
| GET | `/api/presets/{id}/portrait` | Vignette portrait (cache partagé, 404 tant qu'absente) |
| GET/PUT | `/api/mon-profil` | Fiche « dating app » de l'utilisateur (auth Bearer) |
| POST | `/api/mon-profil/photo` | Upload photo (base64) + analyse vision (auth) |
| GET | `/api/mon-profil/photo` | Photo de profil (auth) |
| GET/POST | `/api/sessions` | Liste / création de rencontre (auth Bearer) |
| GET/DELETE | `/api/sessions/{id}` | Profil public / suppression |
| GET | `/api/sessions/{id}/photos` | Album photo |
| POST | `/api/sessions/{id}/photos/regenerer` | Régénérer une photo (même scène, nouvelle seed) |
| WS | `/ws/{id}` | Chat : `join {token}` / `say` / `photo_request` / `game_start` |

## Tests

### Tests unitaires (hors ligne)

```powershell
.venv\Scripts\python -m pytest -q          # 337 tests
```

### Tests LIVE de conformité (serveur démarré)

Deux scripts pilotent l'application comme un vrai client (WebSocket + REST) :
ils **jugent** les réponses du personnage par heuristiques déterministes et,
pour les photos, font décrire chaque image par le **modèle vision** (llama.cpp
multimodal) avant d'en vérifier la conformité. Prérequis : la stack lancée
(`.\scripts\demarrer-serveur.bat`), ComfyUI sur l'hôte (port 8188) et le
projeteur vision chargé (`--no-mmproj-offload`).

```powershell
# 1) Parcours complet d'un personnage : scénarios, mémoire, messages
#    proactifs (gradation + clôture), photos, ton par stade.
.venv\Scripts\python scripts\test_live_conformite.py

# 2) Conformité PAR STADE, sur DEUX personnages (un preset + un personnalisé
#    créé par l'API) — IMAGES et CONVERSATIONS :
#    - images : refus déterministe sous « neutre », génération à neutre /
#      chaleureux / proche, puis conformité VISUELLE (genre, traits du
#      personnage, tenue conforme au stade : sobre à neutre, jamais nue
#      avant proche) ; à « proche » en plus, une demande EXPLICITE (nudité)
#      doit être autorisée — prompt stocké vérifié + nudité constatée par la
#      vision ; l'album ne bouge pas quand la photo est refusée ;
#    - conversations : refus court déterministe au rejet, distance et
#      invitations / sollicitations refusées à froid (malus d'insistance),
#      sujets généraux acceptés mais sexualité refusée à réservé, sujets
#      personnels acceptés et sexualité refusée à neutre, ton investi à
#      chaleureux, familiarité et langage cru acceptés à proche ; aucune
#      offre de photo sous « neutre » ; le stade rapporté reste imposé.
.venv\Scripts\python scripts\test_live_stades.py
#    options : --seulement preset|custom        (un seul personnage)
#              --stades rejet,neutre            (un sous-ensemble de stades)
#              --sans-images / --sans-conversations
```

Les rapports JSON détaillés (verdicts, transcript complet, descriptions
d'images) sont écrits dans `%TEMP%\opencode\` : `rapport_live_conformite.json`
et `rapport_live_stades.json`.

#### Dernier passage de `test_live_stades.py` (117 / 119 PASS)

| | |
|---|---|
| Personnages | preset **Camille Desrosiers** (`camille_desrosiers`) + personnalisé **Nadia Haddad** (architecte, pixie platine) |
| Stades | rejet (50), froid (150), réservé (300), neutre (500), chaleureux (700), proche (900) |
| Images | refus conformes (rejet / froid / réservé, album inchangé) ; génération conforme (neutre / chaleureux / proche) et tenue validée par la **vision** : sobre à neutre, lingerie possible (jamais nue) à chaleureux ; à **proche**, tenue libre et **nudité explicite possible** — prompt autorisant l'explicite et `nudity=yes` constaté à l'image pour les **deux** personnages ; traits reconnus (rousse bouclée / blonde pixie) |
| Conversations | conforme sauf 2 écarts, tous sur le personnage personnalisé : à « froid » une offre de photo *conditionnelle* (« dans quelques jours… ») et à « neutre » une dérobade sans refus franc à une sollicitation sexuelle ; réponses non explicites |
| Global | aucune fuite mécanique, ligne méta ni sortie de rôle |
| **Résultat** | **117 / 119 vérifications PASS** |

> Les réponses d'un LLM étant stochastiques, les scores varient d'un passage à
> l'autre et le personnage joue parfois la nuance (dérobade, temporisation).
> Ces scripts sont conçus pour **signaler** ces écarts, pas pour les masquer.

## 🧾 Licence

Le code de ce dépôt est distribué sous licence [MIT](LICENSE).

Les modèles d'IA ne sont **pas** inclus et **aucune image générée n'est
versionnée** : voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) pour les
licences (Qwen3.5 : Apache 2.0 ; génération d'images recommandée sous licence
permissive — Qwen-Image 1.0 / FLUX.1-schnell, Apache 2.0 ; [copie de la licence
Qwen Research](QWEN_RESEARCH_LICENSE.txt)).
