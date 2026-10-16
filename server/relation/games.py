"""Mini-jeux de conversation — moteur 100 % déterministe côté serveur.

Trois jeux classiques de conversation, lancés par bouton dans le chat :

- **Deux vérités, un mensonge** : le serveur compose 3 énoncés à partir de
  la fiche du personnage (2 vrais, vérifiables dans le profil visible) + 1
  faux (anti-fiche) ; le match devine ; le serveur vérifie — le LLM ne fait
  que réagir et révéler.
- **Action ou vérité** : le serveur choisit le défi / la question dans des
  banques filtrées par stade, colorées par les intérêts du personnage.
- **20 questions** : le serveur choisit un objet secret lié à l'univers du
  personnage (intérêts / métier) avec des indices progressifs ; le match
  pose ses questions (le LLM répond oui/non en incarnation) et devine — la
  victoire est vérifiée par mots-clés côté serveur.

Le LLM ne choisit JAMAIS les contenus ni l'issue d'un jeu : il reçoit une
directive de jeu (build_game_directive) et incarne le personnage autour.
Les points de relation sont déterministes, multipliés par le barème
`gain_multiplier` comme le reste (voir scoring.compute_delta).

Gates par stade (server/relation/stages.can_play_stage) :
- rejet  : aucun jeu (le personnage ne répond plus) ;
- neutre : les trois jeux (brise-glace de l'app une fois la glace brisée) ;
- rien avant « neutre » : à froid, on discute simplement.
"""

from __future__ import annotations

import random
import re
from typing import Any, Optional

from .scoring import _sans_accents
from .stages import can_play_stage

# --------------------------------------------------------------------------- #
#  Types de jeux
# --------------------------------------------------------------------------- #
TYPE_DEUX_VERITES = "deux_verites"
TYPE_ACTION_VERITE = "action_verite"
TYPE_VINGT_QUESTIONS = "vingt_questions"

# Libellés + gate de stade minimale (None = toujours autorisé hors rejet).
JEUX_DISPONIBLES: dict[str, dict[str, Any]] = {
    TYPE_DEUX_VERITES: {
        "label": "Deux vérités, un mensonge",
        "emoji": "🤥",
        "min_stage": "neutre",
    },
    TYPE_ACTION_VERITE: {
        "label": "Action ou vérité",
        "emoji": "🎭",
        "min_stage": "neutre",
    },
    TYPE_VINGT_QUESTIONS: {
        "label": "20 questions",
        "emoji": "❓",
        "min_stage": "neutre",
    },
}

# Barème de base (multiplié par gain_multiplier côté appelant, comme le
# barème de scoring.py).
POINTS_2V1M_GAGNE = 12      # deviner le mensonge : attention + engagement
POINTS_2V1M_PERDU = 4       # participation, le jeu reste une confidence
POINTS_2V1M_MANCHE2 = 6     # manche 2 (« à toi de piéger ») jouée jusqu'au bout
POINTS_AOV_PARTICIPATION = 6  # avoir répondu à l'action / la vérité
POINTS_20Q_GAGNE = 14       # trouvé l'objet secret
POINTS_20Q_PERDU = 4        # 20 questions écoulées : participation
MAX_QUESTIONS_20Q = 20
MAX_INACTIF = 3             # messages hors-jeu avant abandon silencieux


# --------------------------------------------------------------------------- #
#  Aides de mise en forme des contenus du personnage
# --------------------------------------------------------------------------- #
def _minuscule1(s: str) -> str:
    """« L'escalade » → « l'escalade » (pour insérer au milieu d'une phrase)."""
    s = (s or "").strip()
    if len(s) >= 2 and s[1:2].isupper():
        return s  # sigle / prénom composé — on ne touche pas
    return s[:1].lower() + s[1:] if s else s


def _segments_interets(character: dict[str, Any]) -> list[str]:
    """Découpe la chaîne d'intérêts en segments insérables dans une phrase.

    « L'escalade de bloc en salle et la lecture de romans » →
    ["l'escalade de bloc en salle", "la lecture de romans"].
    """
    brut = str(character.get("interests") or "").strip().rstrip(".")
    if not brut:
        return []
    parties = re.split(r"\s+et\s+|\s+ ET \s+|,|;|/", brut)
    return [
        _minuscule1(p.strip())
        for p in parties
        if len(p.strip()) >= 3
    ][:3]


def _occupation_court(character: dict[str, Any]) -> str:
    """Premier segment de l'occupation, s'il est assez court pour une phrase."""
    occ = str(character.get("occupation") or "").strip().rstrip(".")
    if not occ:
        return ""
    seg = re.split(r"[.,;:]", occ)[0].strip()
    if len(seg) < 6 or len(seg) > 60:
        return ""
    return _minuscule1(seg)


def _age(character: dict[str, Any]) -> Optional[int]:
    try:
        return int(str(character.get("age", "")).strip())
    except (TypeError, ValueError):
        return None


def _genre(character: dict[str, Any]) -> str:
    return (character.get("gender") or "").upper()[:1]


# --------------------------------------------------------------------------- #
#  Anti-répétition : historique des contenus déjà utilisés (id bancaire)
# --------------------------------------------------------------------------- #
MAX_HISTORIQUE = 24


def _historique(profile: dict[str, Any]) -> list[str]:
    return [h for h in (profile.get("games_historique") or []) if isinstance(h, str)]


def _marquer_utilise(profile: dict[str, Any], item_id: str) -> None:
    if not item_id:
        return
    hist = profile.setdefault("games_historique", [])
    if item_id not in hist:
        hist.append(item_id)
    del hist[:-MAX_HISTORIQUE]


def _choisir(candidats: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    """Choisit un item de banque en évitant les ids déjà utilisés (recycle si
    tout a été consommé)."""
    utilises = set(_historique(profile))
    frais = [c for c in candidats if c.get("id") not in utilises]
    return random.choice(frais or candidats)


def _candidats_par_stade(
    banque: list[dict[str, Any]], stage: str
) -> list[dict[str, Any]]:
    return [b for b in banque if can_play_stage(b.get("min_stage"), stage)]


# --------------------------------------------------------------------------- #
#  BANQUES — Vérités (Action ou vérité)
#  {interest1} : premier intérêt du personnage. min_stage : gate.
# --------------------------------------------------------------------------- #
BANQUE_VERITES: list[dict[str, Any]] = [
    # — froid : léger, brise-glace, zéro risque —
    {"id": "v_detente", "min_stage": "froid",
     "texte": "C'est quoi ton truc pour te détendre après une longue journée ?"},
    {"id": "v_journee", "min_stage": "froid",
     "texte": "Ta journée parfaite, elle ressemble à quoi ?"},
    {"id": "v_chanson", "min_stage": "froid",
     "texte": "C'est quoi ta chanson coup de cœur en ce moment ?"},
    {"id": "v_talent", "min_stage": "froid",
     "texte": "Ton plus grand talent caché, c'est quoi ?"},
    {"id": "v_cafe", "min_stage": "froid",
     "texte": "Café, thé ou… autre chose ? Réponds vite, c'est important ☕"},
    {"id": "v_horaires", "min_stage": "froid",
     "texte": "Tu es plutôt du genre lève-tôt ou couche-tard ?"},
    {"id": "v_perso", "min_stage": "froid",
     "texte": "Si tu pouvais dîner avec n'importe qui, vivant ou pas, ce serait qui ?"},
    # — réservé : un cran plus personnel, un peu d'humour —
    {"id": "v_manger", "min_stage": "reserve",
     "texte": "C'est quoi le truc le plus étrange que tu aies jamais mangé ?"},
    {"id": "v_rdv", "min_stage": "reserve",
     "texte": "Ton pire rendez-vous galant, il s'est passé quoi exactement ?"},
    {"id": "v_peur", "min_stage": "reserve",
     "texte": "Quelle est ta plus grande peur — honnêtement ?"},
    {"id": "v_reve", "min_stage": "reserve",
     "texte": "C'est quoi ton rêve que tu n'as jamais osé raconter à quelqu'un ?"},
    {"id": "v_gaffe", "min_stage": "reserve",
     "texte": "As-tu déjà fait une gaffe mémorable en public ? Raconte."},
    {"id": "v_gaffe_interet", "min_stage": "reserve",
     "texte": "As-tu déjà fait une gaffe mémorable en pleine séance de {interest1} ? Raconte."},
    # — neutre : personnel, on s'ouvre —
    {"id": "v_fierté", "min_stage": "neutre",
     "texte": "C'est quoi le moment dont tu es le plus fier(ère) ?"},
    {"id": "v_famille", "min_stage": "neutre",
     "texte": "Ton souvenir préféré avec ta famille ou tes amis ?"},
    {"id": "v_plaquer", "min_stage": "neutre",
     "texte": "Si tu devais tout plaquer demain pour te consacrer à {interest1}, tu le ferais ?"},
    {"id": "v_regret", "min_stage": "neutre",
     "texte": "Quelle est la chose dont tu t'en veux le plus ?"},
    {"id": "v_larmes", "min_stage": "neutre",
     "texte": "Qu'est-ce qui te fait vraiment pleurer (films acceptés) ?"},
    # — chaleureux : taquin, complice, jamais explicite —
    {"id": "v_craque", "min_stage": "chaleureux",
     "texte": "C'est quoi ton plus gros craque chez quelqu'un ?"},
    {"id": "v_intrigue", "min_stage": "chaleureux",
     "texte": "Qu'est-ce qui t'a intrigué(e) chez moi depuis qu'on discute ?"},
    {"id": "v_un_soir", "min_stage": "chaleureux",
     "texte": "Ta plus belle histoire d'un soir (ou presque) ?"},
    {"id": "v_baiser", "min_stage": "chaleureux",
     "texte": "Où est-ce que tu aimes qu'on t'embrasse en premier 😏 ?"},
    {"id": "v_match", "min_stage": "chaleureux",
     "texte": "Si on s'était rencontrés en vrai, tu m'aurais « matché » en vrai ? Sois honnête."},
    # — proche : audacieux, couple —
    {"id": "v_fantasme", "min_stage": "proche",
     "texte": "Ton fantasme le plus fou sur nous deux ?"},
    {"id": "v_surnom", "min_stage": "proche",
     "texte": "C'est quoi le surnom que tu n'oses pas encore me donner ?"},
    {"id": "v_revisionne", "min_stage": "proche",
     "texte": "Quel moment passé avec moi tu revis sans cesse 😏 ?"},
    {"id": "v_attente", "min_stage": "proche",
     "texte": "Dis-moi un truc que tu attends encore de moi."},
]

# --------------------------------------------------------------------------- #
#  BANQUES — Actions (défis textuels : pas de photo, pas de rencontre)
# --------------------------------------------------------------------------- #
BANQUE_ACTIONS: list[dict[str, Any]] = [
    # — froid / réservé : drôle, anodin —
    {"id": "a_rimes", "min_stage": "froid",
     "texte": "Écris ton prochain message en rimes."},
    {"id": "a_chanson", "min_stage": "froid",
     "texte": "Chante le refrain de ta chanson préférée (en texto, best effort 🎤)."},
    {"id": "a_reportage", "min_stage": "froid",
     "texte": "Raconte ta journée comme un reportage télé, voix off incluse."},
    {"id": "a_emojis", "min_stage": "froid",
     "texte": "Décris ton humeur du jour avec 3 emojis seulement."},
    {"id": "a_imite", "min_stage": "froid",
     "texte": "Écris ton prochain message comme le dirait ta grand-mère."},
    # — neutre : créatif —
    {"id": "a_galerie", "min_stage": "neutre",
     "texte": "Décris-moi la dernière photo de ta galerie en détail (sans l'envoyer)."},
    {"id": "a_acteur", "min_stage": "neutre",
     "texte": "Réécris ta dernière phrase à la voix de ton personnage de film préféré."},
    {"id": "a_gaffe_interet", "min_stage": "neutre",
     "texte": "Raconte ta pire mésaventure en lien avec {interest1}. Ce doit être croustillant."},
    {"id": "a_compliment", "min_stage": "neutre",
     "texte": "Fais-moi un compliment… mais en commençant par le plus gênant."},
    # — chaleureux : taquin —
    {"id": "a_chuchote", "min_stage": "chaleureux",
     "texte": "Écris ton prochain message en mode chuchoté… (trop de points de suspension interdit 😏)."},
    {"id": "a_nosera", "min_stage": "chaleureux",
     "texte": "Écris-moi un message que tu n'oserais jamais envoyer à quelqu'un d'autre."},
    {"id": "a_profil", "min_stage": "chaleureux",
     "texte": "Fais-moi un compliment sur mon profil — le plus honnête possible 😏"},
    {"id": "a_tenue", "min_stage": "chaleureux",
     "texte": "Décris ce que tu porterais pour notre premier rendez-vous."},
    # — proche : audacieux mais sans explicite graphique —
    {"id": "a_poeme", "min_stage": "proche",
     "texte": "Écris-moi un petit poème (2 vers minimum) sur nous deux."},
    {"id": "a_secret", "min_stage": "proche",
     "texte": "Chuchote-moi un secret que personne d'autre ne connaît."},
    {"id": "a_gene", "min_stage": "proche",
     "texte": "Dis-moi le truc le plus gênant que tu ferais devant moi seulement."},
]


# --------------------------------------------------------------------------- #
#  BANQUES — Objets secrets (20 questions), liés par domaine aux intérêts.
#  indices : du plus vague au plus évident (donnés aux questions 5/10/15).
# --------------------------------------------------------------------------- #
BANQUE_SECRETS: list[dict[str, Any]] = [
    {"id": "tasse_cafe", "nom": "une tasse de café",
     "domaines": ["cafe", "cuisine", "restau", "boulot", "travail"],
     "mots": ["tasse de cafe", "cafe", "mug", "expresso"],
     "indices": ["Je suis souvent brûlant(e)", "On me tient à une main",
                 "On me vide puis on me remplit", "Sans moi le matin, l'humanité gronde"]},
    {"id": "parapluie", "nom": "un parapluie",
     "domaines": ["voyage", "mode", "meteo", "promenade"],
     "mots": ["parapluie"],
     "indices": ["Je ne sors que quand le ciel est de mauvaise humeur",
                 "Je plie sous la pression puis je me remets",
                 "On me perd tout le temps", "Je ressemble à une chauve-souris déployée"]},
    {"id": "livre", "nom": "un livre",
     "domaines": ["lecture", "roman", "livre", "bibliotheque", "science"],
     "mots": ["livre", "roman", "bouquin"],
     "indices": ["Je me consomme page par page",
                 "On me tient couché(e) dans les mains",
                 "J'ai une couverture et une tranche",
                 "On me marque d'un ruban pour me reprendre plus tard"]},
    {"id": "guitare", "nom": "une guitare",
     "domaines": ["musique", "art", "concert", "chanson"],
     "mots": ["guitare"],
     "indices": ["On me gratte", "J'ai six cordes — souvent",
                 "On m'accorde avant chaque spectacle",
                 "En bandoulière, je monte sur scène"]},
    {"id": "chaussures_course", "nom": "des chaussures de course",
     "domaines": ["sport", "course", "running", "gym", "escalade", "entrainement"],
     "mots": ["chaussure", "sneakers", "runner", "basket"],
     "indices": ["On me porte sans que je sois un vêtement",
                 "J'aime l'asphalte et la piste",
                 "Je prends des coups mais j'amortis",
                 "On me lace avant de partir"]},
    {"id": "passeport", "nom": "un passeport",
     "domaines": ["voyage", "voyager", "asie", "europe"],
     "mots": ["passeport"],
     "indices": ["On me demande à chaque frontière",
                 "J'ai une photo qui ne te ressemble pas vraiment",
                 "Je prends l'avion sans jamais payer",
                 "Je collectionne les tampons"]},
    {"id": "chat", "nom": "un chat",
     "domaines": ["animaux", "chat", "chats", "maison"],
     "mots": ["chat", "minou", "felin"],
     "indices": ["Je ronronne quand je suis heureux",
                 "Je dors seize heures par jour",
                 "Je méprise les ordres", "Je me couche sur ton clavier"]},
    {"id": "pinceau", "nom": "un pinceau",
     "domaines": ["art", "peinture", "dessin", "illustration", "design", "bricante", "brocante"],
     "mots": ["pinceau"],
     "indices": ["Je trempe dans la couleur", "J'étale au lieu de parler",
                 "On me rince après chaque séance", "Sans moi, pas de fresque"]},
    {"id": "tente", "nom": "une tente",
     "domaines": ["nature", "camping", "plein air", "randonnee", "voyage", "foret"],
     "mots": ["tente"],
     "indices": ["Je me dresse en quelques minutes",
                 "Je dors deux à quatre personnes",
                 "On me plante", "Je te protège des moustiques la nuit"]},
    {"id": "manette", "nom": "une manette de jeu",
     "domaines": ["jeux video", "jeux", "gaming", "tech", "video"],
     "mots": ["manette", "controller"],
     "indices": ["On me presse les boutons",
                 "Je relie ta main à un monde virtuel",
                 "On me recharge la nuit",
                 "Je finis parfois sous le canapé"]},
    {"id": "echarpe", "nom": "une écharpe",
     "domaines": ["mode", "couture", "vintage", "hiver", "tricot"],
     "mots": ["echarpe"],
     "indices": ["Je t'enroule le cou", "On me tricote",
                 "Je disparais au printemps", "Je vis au fond des placards en été"]},
    {"id": "velo", "nom": "un vélo",
     "domaines": ["velo", "sport", "nature", "randonnee", "promenade", "ville"],
     "mots": ["velo", "bicyclette", "bike"],
     "indices": ["Deux roues, zéro essence", "On me monte et je dévale",
                 "Je prends des coups de pédale", "Je sonne pour me frayer un chemin"]},
    {"id": "ecouteurs", "nom": "des écouteurs",
     "domaines": ["musique", "tech", "podcast", "sport", "telephone"],
     "mots": ["ecouteur", "airpods", "casque audio"],
     "indices": ["On me branche aux oreilles", "Je coupe le monde en un clic",
                 "Je m'emmêle invariablement dans ta poche",
                 "Je vis en paire mais je me perds seul"]},
    {"id": "plante", "nom": "une plante verte",
     "domaines": ["jardinage", "plantes", "maison", "nature", "deco"],
     "mots": ["plante", "fleur", "cactus"],
     "indices": ["Je bois mais je ne parle pas", "On m'arrose le lundi",
                 "Je pousse vers la fenêtre", "On me rempote quand je grandis"]},
    {"id": "appareil_photo", "nom": "un appareil photo",
     "domaines": ["photo", "photographie", "art", "voyage"],
     "mots": ["appareil photo", "camera", "photographie"],
     "indices": ["Je fige le temps", "On me sort aux grands moments",
                 "Je clignote avant de te faire sourire",
                 "Sans moi, pas de souvenirs en image"]},
    {"id": "raquette", "nom": "une raquette",
     "domaines": ["sport", "tennis", "badminton", "compet"],
     "mots": ["raquette"],
     "indices": ["Je frappe une balle", "On me tient par le manche",
                 "On me re-corde", "Je vis dans un sac avec des balles"]},
    {"id": "sac_dos", "nom": "un sac à dos",
     "domaines": ["voyage", "randonnee", "nature", "sport", "escalade", "ecole"],
     "mots": ["sac a dos", "backpack"],
     "indices": ["Je porte tout sur mon dos",
                 "On me boucle les deux sangles",
                 "Je deviens lourd en fin de journée",
                 "Je range l'essentiel et le reste"]},
]


def _mots_interets(character: dict[str, Any]) -> set[str]:
    """Mots normalisés (sans accents) des intérêts du personnage."""
    mots = set()
    for seg in _segments_interets(character):
        mots.update(re.findall(r"[a-z]{3,}", _sans_accents(seg.lower())))
    return mots


def _choisir_secret(character: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Objet secret de préférence lié à un intérêt du personnage."""
    interesses = _mots_interets(character)
    utilises = set(_historique(profile))
    lies = [
        s for s in BANQUE_SECRETS
        if interesses & set(s.get("domaines", [])) and s["id"] not in utilises
    ]
    if lies:
        return random.choice(lies)
    frais = [s for s in BANQUE_SECRETS if s["id"] not in utilises]
    return random.choice(frais or BANQUE_SECRETS)


# --------------------------------------------------------------------------- #
#  Deux vérités, un mensonge — composition des énoncés
# --------------------------------------------------------------------------- #
# Faux métiers plausibles (l'anti-fiche : l'utilisateur peut vérifier la vraie
# fiche dans le panneau d'informations — le jeu récompense l'attention).
FAUX_METIERS = [
    "pilote d'hélicoptère les fins de semaine",
    "prof de yoga à temps partiel",
    "secouriste volontaire",
    "DJ de mariages",
    "guide touristique",
    "barista dans un café à chats",
    "testeur de parcs d'attractions",
]


def _enonces_2v1m(
    character: dict[str, Any], profile: dict[str, Any]
) -> Optional[tuple[list[str], int]]:
    """(3 énoncés mélangés, numéro du mensonge 1-3) ou None si pas assez de
    matière.

    Les énoncés VRAIS sont vérifiables dans la fiche visible du personnage
    (âge, intérêts, métier) ; le mensonge la contredit. Chaque énoncé est
    tiré d'un pool de formulations (variété) avec anti-répétition sur les
    ids (games_historique) — deux parties ne proposent pas les mêmes
    énoncés tant qu'il reste du neuf.
    """
    vraies: list[tuple[str, str]] = []
    fausses: list[tuple[str, str]] = []

    age = _age(character)
    interets = _segments_interets(character)
    occ = _occupation_court(character)

    # --- Énoncés VRAIS (vérifiables dans la fiche visible). --- #
    if age is not None:
        vraies.append(("tv_age1", f"J'ai {age} ans."))
        vraies.append(("tv_age2", f"{age} ans, et bien décidé(e) à en profiter."))
    if interets:
        i1 = interets[0]
        vraies.append(("tv_i1a", f"Mon vrai passe-temps du moment, c'est {i1}."))
        vraies.append(("tv_i1b", f"Je pourrais parler pendant des heures de {i1}."))
        vraies.append(("tv_i1c", f"Mon déclic du moment ? {i1}."))
    if len(interets) >= 2:
        i2 = interets[1]
        vraies.append(("tv_i2a", f"Et je passe aussi pas mal de temps sur {i2}."))
        vraies.append(("tv_i2b", f"L'autre truc qui m'occupe beaucoup : {i2}."))
    if occ:
        vraies.append(("tv_occ1", f"Côté travail : {occ}."))
        vraies.append(("tv_occ2", f"Pour gagner ma vie : {occ}."))

    # --- Énoncés FAUX (l'anti-fiche : vérifiables comme controuvés). --- #
    if interets:
        i1 = interets[0]
        fausses.append(("fv_i1a", f"Je n'ai jamais accroché avec {i1}, franchement pas mon truc."))
        fausses.append(("fv_i1b", f"Je déteste tout ce qui touche à {i1}."))
    if len(interets) >= 2:
        i2 = interets[1]
        fausses.append(("fv_i2a", f"{i2} ? Franchement, je n'ai jamais compris l'attrait."))
    if age is not None:
        faux_age = age + 6 if random.random() < 0.5 else max(18, age - 6)
        if faux_age != age:
            fausses.append(("fv_age1", f"J'ai {faux_age} ans."))
    fausses.append(("fv_occ1", f"Côté travail : {random.choice(FAUX_METIERS)}."))
    fausses.append(("fv_occ2", f"À côté de tout ça, je suis aussi {random.choice(FAUX_METIERS)}."))

    if len(vraies) < 2 or not fausses:
        return None

    utilises = set(_historique(profile))

    def choisir(pool: list[tuple[str, str]], exclus: set[str]) -> tuple[str, str]:
        frais = [
            (cid, texte) for cid, texte in pool
            if f"dv:{cid}" not in utilises and cid not in exclus
        ]
        if not frais:
            frais = [(cid, texte) for cid, texte in pool if cid not in exclus]
        return random.choice(frais or pool)

    v1 = choisir(vraies, set())
    v2 = choisir(vraies, {v1[0]})
    fausse = choisir(fausses, {v1[0], v2[0]})

    # Anti-répétition : les formulations tirées ne reviendront pas avant un
    # long moment (recyclage une fois le pool épuisé).
    for cid in (v1[0], v2[0], fausse[0]):
        _marquer_utilise(profile, f"dv:{cid}")

    enonces = [v1[1], v2[1], fausse[1]]
    random.shuffle(enonces)
    # Index du mensonge en NUMÉROTATION JOUEUR (1-3, comme l'ouverture
    # « 1️⃣ 2️⃣ 3️⃣ » et les devinettes du match).
    return enonces, enonces.index(fausse[1]) + 1


# --------------------------------------------------------------------------- #
#  Ouvertures de jeu (messages déterministes du personnage — aucun LLM)
# --------------------------------------------------------------------------- #
def _ton(stage: str) -> str:
    """Baptême tonal des banques d'ouverture : glace / standard / complice."""
    if stage in ("froid", "reserve"):
        return "glace"
    if stage == "neutre":
        return "standard"
    return "complice"


ACCROCHES_2V1M: dict[str, list[str]] = {
    "glace": [
        "L'app me fait jouer à son petit jeu de glace 😄 Deux vérités et "
        "un mensonge, à toi de deviner :",
    ],
    "standard": [
        "Tu as vu ? L'app nous propose son jeu « deux vérités, un "
        "mensonge » 🤭 Allez, je me lance :",
        "L'app lance son jeu de l'heure 🤭 À moi de piéger — deux vérités "
        "et un mensonge :",
    ],
    "complice": [
        "L'app nous lance son jeu 😏 Deux vérités et un mensonge — à toi "
        "de trouver mon mensonge :",
        "Tiens, l'app nous met au défi 😏 Deux vérités et un mensonge :",
    ],
}

ACCROCHES_AOV: dict[str, list[str]] = {
    "glace": ["L'app nous propose son jeu de glace… 🎭 action ou vérité ?"],
    "standard": [
        "Allons-y, l'app insiste 😄 action ou vérité ? 🎭",
        "Bon, l'app nous lance un défi 🎭 action ou vérité ?",
    ],
    "complice": [
        "L'app nous propose son petit jeu 😏 action ou vérité ? 🎭",
        "Tiens, l'app veut nous voir jouer 😏 action ou vérité ? 🎭",
    ],
}


def _ouverture_2v1m(enonces: list[str], stage: str) -> str:
    accroche = random.choice(ACCROCHES_2V1M[_ton(stage)])
    return (
        f"{accroche}\n"
        f"1️⃣ {enonces[0]}\n"
        f"2️⃣ {enonces[1]}\n"
        f"3️⃣ {enonces[2]}\n\n"
        "Alors… lequel est le mensonge ?"
    )


def _ouverture_aov(stage: str) -> str:
    return random.choice(ACCROCHES_AOV[_ton(stage)])


def _ouverture_20q(character: dict[str, Any]) -> str:
    interets = _segments_interets(character)
    base = "Bon, l'app nous met au défi 🤫 j'ai un truc en tête"
    if interets and random.random() < 0.7:
        base += f", un truc en rapport avec {interets[0]}"
    return (
        f"{base}. Tu as {MAX_QUESTIONS_20Q} questions pour le trouver — "
        "oui ou non, en avant !"
    )


# --------------------------------------------------------------------------- #
#  Démarrage d'un jeu
# --------------------------------------------------------------------------- #
def demarrer_jeu(
    gtype: str, profile: dict[str, Any], stage: str
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Démarre un jeu. Renvoie (état, message d'ouverture) — ou (None, refus).

    Le message d'ouverture est écrit par le serveur (déterministe) et doit
    être ajouté à l'historique comme un message du personnage.
    """
    info = JEUX_DISPONIBLES.get(gtype)
    if info is None:
        return None, "Jeu inconnu."
    if stage == "rejet":
        return None, "Au stade « Rejet », le personnage ne répond plus — impossible de lancer un jeu."
    if not can_play_stage(info["min_stage"], stage):
        label = STAGE_LABELS_MIN.get(info["min_stage"], info["min_stage"])
        return None, (
            f"{info['label']} se débloque au stade « {label} » — trop tôt "
            "pour ce jeu avec ce personnage."
        )
    if profile.get("game"):
        return None, "Un jeu est déjà en cours — termine-le d'abord 😉"
    if profile.get("date"):
        return None, "Un rendez-vous est en cours — le jeu de l'app attendra 😉"

    character = profile.get("character", {}) or {}

    if gtype == TYPE_DEUX_VERITES:
        construit = _enonces_2v1m(character, profile)
        if construit is None:
            return None, (
                "Pas assez de détails dans la fiche de ce personnage pour "
                "piéger « Deux vérités, un mensonge » — essaie « Action ou "
                "vérité » ou « 20 questions » !"
            )
        enonces, mensonge = construit
        jeu = {
            "type": gtype,
            "step": "devine",
            "enonces": enonces,
            "mensonge": mensonge,
            "inactif": 0,
        }
        return jeu, _ouverture_2v1m(enonces, stage)

    if gtype == TYPE_ACTION_VERITE:
        jeu = {"type": gtype, "step": "choix", "invite": None, "inactif": 0}
        return jeu, _ouverture_aov(stage)

    if gtype == TYPE_VINGT_QUESTIONS:
        secret = _choisir_secret(character, profile)
        _marquer_utilise(profile, secret["id"])
        jeu = {
            "type": gtype,
            "step": "en_cours",
            "secret_id": secret["id"],
            "questions": 0,
            "indices_donnes": 0,
            "max": MAX_QUESTIONS_20Q,
            "inactif": 0,
        }
        return jeu, _ouverture_20q(character)

    return None, "Jeu inconnu."


STAGE_LABELS_MIN = {
    "froid": "Froid",
    "reserve": "Réservé",
    "neutre": "Neutre",
    "chaleureux": "Chaleureux",
    "proche": "Proche",
}


# --------------------------------------------------------------------------- #
#  Résolution d'un tour de jeu (appelée AVANT le prompt LLM)
# --------------------------------------------------------------------------- #
_CHIFFRES_MOTS = {"un": "1", "une": "1", "deux": "2", "trois": "3"}

_MOTS_ABANDON = ("abandon", "stop")


def _devine_index(text: str) -> Optional[int]:
    """Détecte le numéro désigné dans un message (chiffre ou mot court).

    - chiffres : « le 2 », « numéro 3 », « 1 » — le DERNIER chiffre isolé
      gagne (« le 1 ou le 2… allez, le 2 » → 2) ;
    - mots : « le deux », « je dis trois » — uniquement en DERNIER mot d'un
      message court, sinon « j'ai un truc » serait un vote pour l'énoncé 1.
    """
    na = _sans_accents((text or "").lower())
    chiffres = re.findall(r"(?<!\d)([1-3])(?!\d)", na)
    if chiffres:
        return int(chiffres[-1])
    mots = na.split()
    if len(mots) <= 4:
        dernier = mots[-1].strip(".,!?;:…") if mots else ""
        if dernier in _CHIFFRES_MOTS:
            return int(_CHIFFRES_MOTS[dernier])
    return None


def _detecte_choix_aov(text: str) -> Optional[str]:
    """« action » ou « vérité » dans un message court ou explicite."""
    na = _sans_accents((text or "").lower())
    hits = []
    if re.search(r"\baction\b", na):
        hits.append("action")
    if re.search(r"\bverite\b", na):
        hits.append("verite")
    if not hits:
        return None
    return hits[-1]


def _est_abandon(text: str) -> bool:
    na = _sans_accents((text or "").lower())
    return "stop" == na.strip() or any(m in na for m in ("abandon", "j'arrete", "j arrete"))


def _secret_par_id(secret_id: str) -> Optional[dict[str, Any]]:
    return next((s for s in BANQUE_SECRETS if s["id"] == secret_id), None)


def traiter_message_jeu(
    profile: dict[str, Any], text: str, stage: str
) -> Optional[dict[str, Any]]:
    """Résout un tour de jeu si un jeu est actif — sinon None.

    Renvoie un dict :
      points        : int — barème de base (multiplié par l'appelant)
      mode          : « remplace » (le message n'est qu'un choix de jeu) ou
                      « ajoute » (message de conversation + bonus de jeu)
      directive     : str — bloc injecté au LLM pour ce tour ("" si aucun)
      fin           : bool — le jeu se termine (l'appelant vide profile["game"])
    Mutations : profile["game"] mis à jour (tentatives, compteur…) —
    l'appelant persiste via st.save.
    """
    jeu = profile.get("game")
    if not jeu or stage == "rejet":
        return None

    gtype = jeu.get("type")

    if gtype == TYPE_DEUX_VERITES and jeu.get("step") == "devine":
        idx = _devine_index(text)
        if idx is None or not 1 <= idx <= 3:
            jeu["inactif"] = int(jeu.get("inactif", 0)) + 1
            if jeu["inactif"] >= MAX_INACTIF:
                profile["game"] = None
                return {"points": 0, "mode": "remplace", "directive": "", "fin": True}
            return None  # conversation ordinaire, le jeu reste ouvert
        mensonge = int(jeu.get("mensonge", 0))
        enonce_mensonge = (jeu.get("enonces") or ["", "", ""])[mensonge - 1]
        gagne = idx == mensonge
        # Manche 2 : l'app invite le match à piéger à son tour (il/elle
        # reste un humain qui joue, jamais un bot de jeu).
        jeu["step"] = "inverse"
        jeu["inactif"] = 0
        if gagne:
            directive = (
                "[MINI-JEU DE L'APP — RÉSOLUTION (Deux vérités, un mensonge)\n"
                f"Ton match vient de désigner l'énoncé {idx} : c'était BON, "
                "il/elle a trouvé le mensonge. Réagis en personnage (avoue "
                "ta défaite avec humour, selon ta personnalité), RÉVÈLE "
                f"pourquoi l'énoncé mensonger était faux — c'était l'énoncé "
                f"{mensonge} : « {enonce_mensonge} » — et raconte la vraie "
                "version en une phrase.\n"
                "ET ENSUITE : l'app lance la MANCHE 2 — invite ton match à "
                "piéger à son tour, enjoué(e) (ex. « à toi de jouer, "
                "envoie tes deux vérités et un mensonge ! »). Tu restes un "
                "humain qui joue à un jeu de l'application — jamais un "
                "robot de jeu. Ne mentionne jamais la mécanique côté "
                "système.]"
            )
            return {"points": POINTS_2V1M_GAGNE, "mode": "remplace",
                    "directive": directive, "fin": False}
        directive = (
            "[MINI-JEU DE L'APP — RÉSOLUTION (Deux vérités, un mensonge)\n"
            f"Ton match a désigné l'énoncé {idx} : il/elle s'est TROMPÉ(e). "
            f"Le mensonge était l'énoncé {mensonge} : « {enonce_mensonge} ». "
            "Savoure ta victoire avec ta personnalité (taquine si le stade le "
            "permet), révèle ce qui rendait l'énoncé faux et la vraie "
            "histoire derrière les deux vrais énoncés.\n"
            "ET ENSUITE : l'app lance la MANCHE 2 — invite ton match à "
            "piéger à son tour, enjoué(e) (ex. « à toi de piéger, envoie "
            "tes deux vérités et un mensonge ! »). Tu restes un humain qui "
            "joue à un jeu de l'application — jamais un robot de jeu. Ne "
            "mentionne jamais la mécanique côté système.]"
        )
        return {"points": POINTS_2V1M_PERDU, "mode": "remplace",
                "directive": directive, "fin": False}

    if gtype == TYPE_DEUX_VERITES and jeu.get("step") == "inverse":
        # Le joueur envoie ses propres énoncés (numérotés, ou le mot
        # « mensonge ») → le personnage devine.
        na_inv = _sans_accents((text or "").lower())
        chiffres = re.findall(r"(?<!\d)[1-3](?!\d)", na_inv)
        declares = (
            "mensonge" in na_inv
            or len(chiffres) >= 2
            or (text or "").count("\n") >= 2
        )
        if not declares:
            # Refus poli de la manche 2 ou babillage.
            if any(m in na_inv for m in ("pas maintenant", "pas envie",
                                         "pas tout de suite", "abandon",
                                         "stop")):
                profile["game"] = None
                return {"points": 0, "mode": "remplace", "directive": "", "fin": True}
            jeu["inactif"] = int(jeu.get("inactif", 0)) + 1
            if jeu["inactif"] >= MAX_INACTIF:
                profile["game"] = None
                return {"points": 0, "mode": "remplace", "directive": "", "fin": True}
            return None
        jeu["step"] = "inverse_devine"
        jeu["inactif"] = 0
        directive = (
            "[MINI-JEU DE L'APP — MANCHE 2 (à toi de deviner)\n"
            "Ton match vient d'envoyer SES deux vérités et un mensonge via "
            "le jeu de l'app : « " + (text or "")[:400] + " ».\n"
            "Devine lequel est le mensonge en t'appuyant sur ce que tu "
            "connais déjà de lui/d'elle et sur ta lecture de ses énoncés : "
            "engage-toi sur UNE réponse (énoncé 1, 2 ou 3) avec ta "
            "personnalité, ton argument en une phrase — et attends sa "
            "révélation. Ne mentionne jamais la mécanique côté système.]"
        )
        return {"points": 0, "mode": "remplace", "directive": directive,
                "fin": False}

    if gtype == TYPE_DEUX_VERITES and jeu.get("step") == "inverse_devine":
        # La révélation du joueur clôt la manche 2 (participation récompensée).
        na_rev = _sans_accents((text or "").lower())
        _REVELE = (
            "gagne", "gagné", "gagnee", "trouve", "trouvé", "bravo",
            "bien joue", "bien joué", "exact", "c'est ca", "cest ca",
            "c'est ça", "tu as trouve", "tu as trouvé", "tu as devine",
            "tu as deviné", "perdu", "rate", "raté", "faux", "pas ca",
            "pas ça", "c'est le", "cest le", "c'est pas",
        )
        if any(m in na_rev for m in _REVELE) or len(na_rev.split()) >= 6:
            profile["game"] = None
            directive = (
                "[MINI-JEU DE L'APP — FIN DE LA MANCHE 2\n"
                "Ton match vient de se prononcer sur ta devinette : « "
                f"{(text or '')[:200]} ». Réagis au résultat en personnage "
                "(fière/fier si gagné, boudeuse/boudeur amusé si raté), "
                "révèle ton propre mensonge et sa vraie histoire, puis "
                "enchaîne naturellement. Ne mentionne jamais la mécanique "
                "côté système.]"
            )
            return {"points": POINTS_2V1M_MANCHE2, "mode": "ajoute",
                    "directive": directive, "fin": True}
        jeu["inactif"] = int(jeu.get("inactif", 0)) + 1
        if jeu["inactif"] >= MAX_INACTIF:
            profile["game"] = None
            return {"points": 0, "mode": "remplace", "directive": "", "fin": True}
        return None

    if gtype == TYPE_ACTION_VERITE:
        if jeu.get("step") == "choix":
            choix = _detecte_choix_aov(text)
            if not choix:
                jeu["inactif"] = int(jeu.get("inactif", 0)) + 1
                if jeu["inactif"] >= MAX_INACTIF:
                    profile["game"] = None
                    return {"points": 0, "mode": "remplace", "directive": "", "fin": True}
                return None
            banque = BANQUE_ACTIONS if choix == "action" else BANQUE_VERITES
            candidats = _candidats_par_stade(banque, stage) or banque
            invite = _choisir(candidats, profile)
            _marquer_utilise(profile, invite["id"])
            texte = invite["texte"].replace(
                "{interest1}",
                _segments_interets(profile.get("character", {}) or {})[0]
                if _segments_interets(profile.get("character", {}) or {})
                else "ton passe-temps préféré",
            )
            jeu["step"] = "reponse"
            jeu["invite"] = texte
            jeu["inactif"] = 0
            quoi = "ce DÉFI" if choix == "action" else "cette VÉRITÉ"
            directive = (
                "[MINI-JEU — Action ou vérité\n"
                f"Ton match a choisi « {choix} ». Pose-lui {quoi} en "
                "l'adaptant à ta façon de parler (adapte les accords au "
                f"genre si besoin) : « {texte} ». UNE seule demande, ton "
                "naturel, puis attends sa réponse — ne réponds pas à sa "
                "place. Ne mentionne jamais la mécanique du jeu côté "
                "système.]"
            )
            return {"points": 0, "mode": "remplace", "directive": directive,
                    "fin": False}
        # step « reponse » : n'importe quel message = la réponse.
        profile["game"] = None
        directive = (
            "[MINI-JEU — RÔLES CLAIRS (Action ou vérité)\n"
            "Ton match vient de répondre à TON action/TA vérité — c'est "
            "LUI/ELLE qui se livre, pas toi. Le texte de sa réponse : « "
            f"{(text or '')[:300]} ».\n"
            "Réagis UNIQUEMENT à CE qu'il/elle a révélé : empathie, rire, "
            "teasing selon ta personnalité et le stade de la relation.\n"
            "INTERDITS ABSOLUS : répondre à la question à sa place, "
            "raconter TES propres peurs/secrets à la place de réagir aux "
            "siens, inventer des règles ou un score (« tu as gagné », « tu "
            "as perdu », « manche », « règles du jeu ») — ce jeu n'a "
            "NI gagnant NI perdant, c'est juste une conversation.\n"
            "Puis enchaîne naturellement (poser une nouvelle question à "
            "ton tour est humain — c'est de la curiosité, pas une règle). "
            "Ne mentionne jamais la mécanique du jeu côté système.]"
        )
        return {"points": POINTS_AOV_PARTICIPATION, "mode": "ajoute",
                "directive": directive, "fin": True}

    if gtype == TYPE_VINGT_QUESTIONS and jeu.get("step") == "en_cours":
        secret = _secret_par_id(str(jeu.get("secret_id", "")))
        if secret is None:  # banque mutée entre-temps : clôture proprement
            profile["game"] = None
            return {"points": 0, "mode": "remplace", "directive": "", "fin": True}

        na = _sans_accents((text or "").lower())
        if _est_abandon(text):
            profile["game"] = None
            directive = (
                "[MINI-JEU — RÉSOLUTION (20 questions)\n"
                f"Ton match abandonne : révèle la réponse — c'était "
                f"« {secret['nom']} » — avec ta personnalité, ajoute un "
                "détail amusant sur cet objet, puis enchaîne naturellement. "
                "Ne mentionne jamais la mécanique du jeu côté système.]"
            )
            return {"points": 0, "mode": "remplace", "directive": directive,
                    "fin": True}

        # Victoire : mot-clé de la réponse + message court (une vraie
        # tentative de devinette, pas « j'adore le café » en passant).
        if len(na) <= 80:
            for mot in secret.get("mots", []):
                if re.search(rf"\b{re.escape(mot)}\b", na):
                    profile["game"] = None
                    directive = (
                        "[MINI-JEU — RÉSOLUTION (20 questions)\n"
                        f"Ton match A TROUVÉ : la réponse était "
                        f"« {secret['nom']} ». Félicite-le/la avec ta "
                        "personnalité, avoue (avec humour) si c'était facile "
                        "ou difficile, puis enchaîne naturellement. Ne "
                        "mentionne jamais la mécanique du jeu côté système.]"
                    )
                    return {"points": POINTS_20Q_GAGNE, "mode": "remplace",
                            "directive": directive, "fin": True}

        # Une vraie question (contient « ? ») fait avancer le compteur.
        if "?" in text:
            jeu["questions"] = int(jeu.get("questions", 0)) + 1
            jeu["inactif"] = 0
            questions = jeu["questions"]
            max_q = int(jeu.get("max", MAX_QUESTIONS_20Q))
            if questions >= max_q:
                profile["game"] = None
                directive = (
                    "[MINI-JEU — RÉSOLUTION (20 questions)\n"
                    f"Les {max_q} questions sont écoulées sans que ton match "
                    f"trouve : révèle la réponse — c'était "
                    f"« {secret['nom']} » — moque-toi en gentiment avec ta "
                    "personnalité, raconte un détail sur cet objet, puis "
                    "enchaîne naturellement. Ne mentionne jamais la "
                    "mécanique du jeu côté système.]"
                )
                return {"points": POINTS_20Q_PERDU, "mode": "ajoute",
                        "directive": directive, "fin": True}
            # Indice progressif aux questions 5 / 10 / 15.
            palier = questions // 5
            directive = (
                "[MINI-JEU EN COURS — 20 QUESTIONS\n"
                f"Tu joues à « 20 questions » avec ton match. L'objet auquel "
                f"tu penses : « {secret['nom']} ». RÈGLES : réponds à ses "
                "questions par oui / non / parfois (courtes réponses, ton "
                "naturel) ; ne nomme JAMAIS l'objet directement et ne le "
                "définis pas complètement : c'est LUI qui doit deviner. "
                f"Question en cours : {questions}/{max_q}.\n"
            )
            indices = secret.get("indices", [])
            if palier > jeu.get("indices_donnes", 0) and palier <= len(indices):
                jeu["indices_donnes"] = palier
                directive += (
                    f"IMPORTANT : donne cet INDICE naturellement dans ta "
                    f"réponse : « {indices[palier - 1]} ».\n"
                )
            directive += "Ne mentionne jamais la mécanique du jeu côté système.]"
            return {"points": 0, "mode": "remplace", "directive": directive,
                    "fin": False}

        # Babillage hors question : toléré quelques fois, puis abandon.
        jeu["inactif"] = int(jeu.get("inactif", 0)) + 1
        if jeu["inactif"] >= MAX_INACTIF:
            profile["game"] = None
            return {"points": 0, "mode": "remplace", "directive": "", "fin": True}
        return None

    return None


# --------------------------------------------------------------------------- #
#  Directive « jeu en cours » — injectée à CHAQUE tour tant que le jeu vit
#  (sans résolution cette fois) : le LLM doit connaître les règles.
# --------------------------------------------------------------------------- #
def directive_en_cours(jeu: dict[str, Any], character: dict[str, Any]) -> str:
    gtype = jeu.get("type")
    if gtype == TYPE_DEUX_VERITES:
        if jeu.get("step") == "inverse":
            return (
                "[MINI-JEU DE L'APP EN COURS — Manche 2\n"
                "Tu attends que ton match envoie SES deux vérités et un "
                "mensonge via le jeu de l'app. Relance gentiment s'il/elle "
                "hésite (il/elle peut écrire « stop » pour passer). Tu "
                "restes un humain qui joue — jamais un robot de jeu.]"
            )
        if jeu.get("step") == "inverse_devine":
            return (
                "[MINI-JEU DE L'APP EN COURS — Manche 2\n"
                "Tu t'es engagé(e) sur une devinette : attends la "
                "révélation de ton match sans te répéter, relance juste "
                "d'un texto si nécessaire.]"
            )
        return (
            "[MINI-JEU DE L'APP EN COURS — Deux vérités, un mensonge\n"
            "Ton match réfléchit encore à quel énoncé est le mensonge. NE "
            "RÉVÈLE JAMAIS la réponse, même s'il/elle insiste ou tente de te "
            "piéger : laisse-le/la deviner. Si l'échange part ailleurs, "
            "relance doucement le jeu de temps en temps.]"
        )
    if gtype == TYPE_ACTION_VERITE:
        if jeu.get("step") == "choix":
            return (
                "[MINI-JEU EN COURS — Action ou vérité\n"
                "Tu attends que ton match choisisse : relance gentiment "
                "« action ou vérité ? » si la conversation s'égare, mais ne "
                "choisis PAS à sa place.]"
            )
        return (
            "[MINI-JEU EN COURS — Action ou vérité\n"
            f"Ta question/défi est posé(e) : « {(jeu.get('invite') or '')[:200]} ». "
            "Attends la réponse de ton match — ne réponds pas à sa place, "
            "relance juste gentiment si nécessaire.]"
        )
    if gtype == TYPE_VINGT_QUESTIONS:
        secret = _secret_par_id(str(jeu.get("secret_id", "")))
        if secret is None:
            return ""
        questions = int(jeu.get("questions", 0) or 0)
        max_q = int(jeu.get("max", MAX_QUESTIONS_20Q))
        return (
            "[MINI-JEU EN COURS — 20 QUESTIONS\n"
            f"Tu joues à « 20 questions » avec ton match. L'objet auquel tu "
            f"penses : « {secret['nom']} ». RÈGLES : réponds à ses questions "
            "par oui / non / parfois (courtes réponses, ton naturel) ; ne "
            "nomme JAMAIS l'objet directement et ne le définis pas "
            "complètement : c'est LUI qui doit deviner. "
            f"Question en cours : {questions}/{max_q}. "
            "Ne mentionne jamais la mécanique du jeu côté système.]"
        )
    return ""


# --------------------------------------------------------------------------- #
#  Vue « publique » de l'état du jeu — envoyée au client (SANS les secrets :
#  ni l'index du mensonge, ni l'objet des 20 questions).
# --------------------------------------------------------------------------- #
def jeu_public(jeu: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not jeu:
        return None
    gtype = jeu.get("type")
    if gtype == TYPE_DEUX_VERITES:
        step = jeu.get("step")
        if step == "inverse":
            return {
                "type": gtype,
                "label": "Jeu - à toi de piéger !",
                "chips": [],
            }
        if step == "inverse_devine":
            return {
                "type": gtype,
                "label": "Jeu - révéle ton mensonge !",
                "chips": [],
            }
        return {
            "type": gtype,
            "label": "Jeu - devine le mensonge !",
            "chips": ["1", "2", "3"],
        }
    if gtype == TYPE_ACTION_VERITE:
        if jeu.get("step") == "choix":
            return {
                "type": gtype,
                "label": "Action ou vérité — choisis !",
                "chips": ["Action", "Vérité"],
            }
        return {
            "type": gtype,
            "label": "Action ou vérité — à toi de jouer !",
            "chips": [],
        }
    if gtype == TYPE_VINGT_QUESTIONS:
        max_q = int(jeu.get("max", MAX_QUESTIONS_20Q))
        questions = min(int(jeu.get("questions", 0) or 0) + 1, max_q)
        return {
            "type": gtype,
            "label": f"20 questions — question {questions}/{max_q}",
            "chips": ["J'abandonne 🛑"],
        }
    return None


# --------------------------------------------------------------------------- #
#  Points — même multiplication que le barème de scoring (gain_multiplier)
# --------------------------------------------------------------------------- #
def appliquer_multiplicateur(points: int, gain_multiplier: float) -> int:
    try:
        m = max(0.0, float(gain_multiplier))
    except (TypeError, ValueError):
        m = 1.0
    return int(points * m + 0.5) if points >= 0 else -int(-points * m + 0.5)
