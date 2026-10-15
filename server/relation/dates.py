"""Scénarios interactifs (« rendez-vous ») — le réalisateur invisible.

Extension du système de scénarios (server/relation/presets.py) : au lieu
d'un monologue isolé, le serveur enchaîne une SÉQUENCE de beats narratifs
avec une réponse attendue du joueur — le tout 100 % en conversation
naturelle, sans aucune interface dédiée (le joueur ne voit jamais la
mécanique) :

1. Le serveur choisit un scénario disponible au stade courant (cooldown,
   anti-répétition) et injecte la PROPOSITION : le personnage invite
   naturellement en texto ;
2. Le tour suivant, la réponse du joueur est classée DÉTERMINISTEMENT
   (mots-clés, même philosophie que scoring.compute_delta) :
   acceptée / refusée / évasive — évasion = une relance douce, puis
   laisser-aller avec dignité ;
3. Acceptée → les beats se jouent un par tour ; certains beats portent un
   « moment clé » à options détectées par mots-clés (choix implicites du
   joueur, jamais des boutons) ;
4. Conclusion → points de relation, photo souvenir, souvenir rangé en
   mémoire (« notre premier café ») que le personnage réutilisera.

Le LLM reçoit à chaque tour une directive de scène et incarne le
personnage — il ne décide ni de l'issue ni des étapes.

Gates par stade : aucun rendez-vous avant « neutre » (à froid/réservé, on
discute simplement — une invitation serait prématurée) ; à « neutre »,
les activités à distance (mode « distance » : film synchronisé, playlist,
cuisine chacun chez soi) sont crédibles même sans s'être rencontrés ; les
rencontres en vrai (mode « presentiel ») et les moments de couple
suivent leur progression naturelle.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from .scoring import _sans_accents
from .stages import can_play_stage

# --------------------------------------------------------------------------- #
#  Constantes
# --------------------------------------------------------------------------- #
POINTS_ACCEPTATION = 4     # avoir dit oui à un rendez-vous
POINTS_CONCLUSION = 10     # avoir vécu le rendez-vous jusqu'au bout
MAX_RELANCES = 1           # évasions tolérées après la proposition
MIN_INTERACTIONS = 3       # un minimum d'échanges avant une proposition


# --------------------------------------------------------------------------- #
#  BANQUE DE SCÉNARIOS — 2 par stade (froid → proche).
#  - "proposal" / "scene" / "conclusion" : directives à la 2e personne (« tu
#    es {name}… ») que le LLM incarne en texto ;
#  - {interest1} : premier intérêt du personnage (interpolation serveur) ;
#  - "reponses" : mots-clés de la réponse attendue (sans accents) ;
#  - "moment" : choix implicites détectés par mots-clés, avec scène dédiée
#    et scène par défaut si rien n'est reconnu ;
#  - "photo": "deux" → photo souvenir à deux (édition d'image à partir de la
#    photo de profil du joueur, stades neutre+) après le beat concerné.
# --------------------------------------------------------------------------- #
BANQUE_DATES: list[dict[str, Any]] = [
    # ============================ FROID ============================ #
    {
        "id": "film_sync",
        "titre": "Le film synchronisé",
        "min_stage": "neutre",
        "mode": "distance",
        "proposal": (
            "Tu propose à ton match de regarder LE MÊME film en même temps "
            "ce soir, chacun chez soi, en se commentant la soirée par texto "
            "(c'est ton idée, tu as envie de rompre la glace autrement que "
            "par de simples messages). Choisis un film cohérent avec tes "
            "goûts, donne l'heure, et propose-lui de se donner la réplique "
            "en direct."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "hate", "je suis in",
                        "bonne idee", "cool", "ok", "oui", "c'est parti",
                        "cest parti", "j'en suis", "jen suis", "excellent"],
            "refuse": ["pas possible", "pas ce soir", "pas envie", "je peux pas",
                       "je peux pas", "impossible", "une autre fois", "pas pret",
                       "pas prete", "occupe", "debordé", "deborde", "pas le temps"],
        },
        "beats": [
            {
                "scene": (
                    "C'est le soir du film synchronisé : tu décris ton "
                    "installation (plaid, popcorn, lumières baissées), tu "
                    "annonces que tu lances le film, et tu demandes au match "
                    "de faire pareil — tu proposes qu'on se note nos "
                    "réactions en live."
                ),
            },
            {
                "scene": (
                    "Le film commence. Tu réagis aux premières scènes avec "
                    "ton humour naturel, puis tu demandes au match : "
                    "lui, il aurait plutôt choisi une COMÉDIE ou un "
                    "THRILLER ce soir ? Fais-lui dire."
                ),
                "moment": {
                    "options": {
                        "comedie": ["comedie", "rire", "drôle", "drole", "fun"],
                        "thriller": ["thriller", "suspense", "peur", "horreur"],
                    },
                    "scenes": {
                        "comedie": (
                            "Le match penche pour la comédie : tu t'en "
                            "réjouis, tu avoues que tu avais aussi un plan B "
                            "comédie en réserve, et vous commentez les "
                            "meilleures blagues du film."
                        ),
                        "thriller": (
                            "Le match aime les frissons : tu avoues que tu "
                            "saisies à chaque sursaut et vous commentez les "
                            "tensions du film, un peu complices malgré la "
                            "distance."
                        ),
                        "_defaut": (
                            "Le match donne son avis sur le film : tu rebondis "
                            "avec ta propre réaction et vous continuez à "
                            "commenter la soirée ensemble."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Le film se termine. Tu donnes ta note sur 10, tu "
                    "demandes la sienne, et tu avoues que l'expérience à "
                    "distance était étonnamment sympa."
                ),
            },
        ],
        "conclusion": (
            "Vous avez fini le film : tu conclus la soirée avec chaleur mesurée "
            "(stade oblige) — c'était une belle surprise, tu proposes qu'on "
            "refasse ça un soir."
        ),
        "souvenir": "notre soirée film synchronisé",
    },
    {
        "id": "playlist",
        "titre": "La playlist de la semaine",
        "min_stage": "neutre",
        "mode": "distance",
        "proposal": (
            "Tu annonce à ton match que tu viens de préparer une playlist de "
            "cinq morceaux « pour mieux se connaître » et tu lui propose de "
            "l'écouter et de te dire son morceau préféré. Décris l'ambiance "
            "générale de la playlist en lien avec tes goûts."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "hate", "bonne idee",
                        "cool", "ok", "oui", "j'ecoute", "jecoute", "avec plaisir"],
            "refuse": ["pas le temps", "pas envie", "pas mon style", "je passe",
                       "une autre fois", "je peux pas", "je ne peux pas"],
        },
        "beats": [
            {
                "scene": (
                    "Le match a écouté la playlist : tu attendais son avis "
                    "avec une petite impatience avouée, et tu demandes son "
                    "morceau préféré en promettant de raconter l'histoire du "
                    "tien."
                ),
                "moment": {
                    "options": {
                        "doux": ["doux", "calme", "plaine", "piano", "slow"],
                        "rythme": ["rythme", "rythmé", "rythme", "energie",
                                   "énergie", "danse", "upbeat"],
                    },
                    "scenes": {
                        "doux": (
                            "Le match a préféré le morceau le plus doux : tu "
                            "avoues que c'était celui que tu as mis en "
                            "premier, précisément parce qu'il te ressemble, "
                            "et tu racontes le souvenir qui y est lié."
                        ),
                        "rythme": (
                            "Le match a préféré le plus rythmé : tu ris, tu "
                            "avoues que c'est celui sur lequel tu danses "
                            "dans ta cuisine, et tu racontes dans quel "
                            "contexte tu l'as découvert."
                        ),
                        "_defaut": (
                            "Le match partage son morceau préféré : tu "
                            "rebondis avec plaisir et tu racontes l'histoire "
                            "derrière ton préféré à toi."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "La conversation musique bat son plein : tu demandes au "
                    "match ce qu'il écoute en boucle en ce moment et tu "
                    "promets d'aller écouter — tu t'y engages vraiment."
                ),
            },
        ],
        "conclusion": (
            "Tu conclus l'échange musique : tu dis que tu penseras à "
            "lui/elle en écoutant sa suggestion, et tu proposes de refaire "
            "l'exercice la semaine prochaine avec ta playlist numéro 2."
        ),
        "souvenir": "notre échange playlist",
    },
    # =========================== RÉSERVÉ =========================== #
    {
        "id": "cuisine_sync",
        "titre": "Le défi cuisine à distance",
        "min_stage": "neutre",
        "mode": "distance",
        "proposal": (
            "Tu propose un défi à ton match : cuisiner LE MÊME plat chacun "
            "chez soi ce week-end (choisis un plat simple et parlant, en "
            "lien avec ta passion de {interest1} si c'est culinaire, sinon "
            "ton plat signature), et comparer les résultats par texto. Tu "
            "assumes que c'est un peu espiègle comme idée."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "bonne idee", "cool",
                        "ok", "oui", "je suis chef", "chef", "hate", "hâte",
                        "avec plaisir", "j'adore cuisiner"],
            "refuse": ["je cuisines mal", "je cuisine mal", "pas le temps",
                       "pas envie", "une autre fois", "je mange tout prêt",
                       "je ne sais pas cuisiner"],
        },
        "beats": [
            {
                "scene": (
                    "Jour J : tu décris ta cuisine en mode préparation "
                    "(ingrédients étalés, musique, tablier), tu envoies la "
                    "recette au match et tu le nargues gentiment — que le "
                    "meilleur gagne."
                ),
            },
            {
                "scene": (
                    "Pendant la cuisson, tu racontes ta catastrophe "
                    "presque-arrivée (beurre qui déborde, fumée…) et tu "
                    "demandes au match comment la sienne se passe : "
                    "RÉUSSITE parfaite ou CATASTROPHE totale — exige une "
                    "réponse claire, c'est le cœur du défi."
                ),
                "moment": {
                    "options": {
                        "reussi": ["reussi", "réussi", "parfait", "réussie", "reussie"],
                        "rate": ["rate", "raté", "catastrophe", "brûlé", "brule", "fumé"],
                    },
                    "scenes": {
                        "reussi": (
                            "Le plat du match est une réussite : tu fais "
                            "semblant de bougonner — il va falloir te "
                            "battre — et tu décris fièrement le tien."
                        ),
                        "rate": (
                            "Le plat du match est un désastre : tu ris de "
                            "bon cœur, tu le réconfortes et tu avoues TES "
                            "propres ratages légendaires en cuisine."
                        ),
                        "_defaut": (
                            "Le match décrit sa cuisine en cours : tu "
                            "rebondis avec ton propre avancement et un "
                            "conseil de dernière minute."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Verdict final : vous comparez vos plats. Tu décris le "
                    "goût, tu sors ton plus beau compliment concurrent et "
                    "tu proposes une revanche culinaire bientôt."
                ),
            },
        ],
        "conclusion": (
            "Tu clôture le défi cuisine : même à distance, cuisiner « "
            "ensemble » était étonnamment complice — tu proposes d'en "
            "refaire un la semaine prochaine, ou de goûter le plat de "
            "l'autre un jour."
        ),
        "souvenir": "notre défi cuisine à distance",
    },
    {
        "id": "balade_commentee",
        "titre": "La balade commentée",
        "min_stage": "neutre",
        "mode": "distance",
        "proposal": (
            "Tu propose une balade commentée à distance : ce week-end, "
            "chacun marche de son côté et se raconte ce qu'il voit par "
            "texto, comme deux correspondants de voyage. Tu promets de "
            "montrer ton quartier sous son meilleur angle."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "bonne idee", "cool",
                        "ok", "oui", "j'aime marcher", "jaime marcher", "hate",
                        "hâte", "avec plaisir"],
            "refuse": ["pas le temps", "pas envie", "il fait trop froid",
                       "il fait trop chaud", "une autre fois", "je marche pas",
                       "je ne sors pas ce week-end"],
        },
        "beats": [
            {
                "scene": (
                    "Samedi, tu es en marche : tu décris ton quartier avec "
                    "des détails vivants (odeurs, bruits, une scène "
                    "cocasse), comme un reportage de terrain, et tu "
                    "demandes au match de décrire le sien."
                ),
                "moment": {
                    "options": {
                        "ville": ["ville", "urbain", "downtown", "centre-ville", "rue"],
                        "nature": ["nature", "bois", "parc", "lac", "riviere", "rivière", "campagne"],
                    },
                    "scenes": {
                        "ville": (
                            "Le match vit en pleine ville : vous comparez "
                            "vos centres-ville (traffic, cafés, les gens "
                            "dans la rue) et tu avoues ce que tu préfères "
                            "dans le tien."
                        ),
                        "nature": (
                            "Le match marche côté nature : tu avoues une "
                            "petite pointe d'envie, vous comparez vos "
                            "paysages et tu promets d'aller voir son coin "
                            "un jour."
                        ),
                        "_defaut": (
                            "Le match décrit son coin : tu rebondis avec "
                            "curiosité et vous continuez la balade "
                            "commentée, chacun de son côté."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Tu arrives à ton spot préféré : tu le décris avec "
                    "émotion (c'est là que tu viens réfléchir) et tu poses "
                    "une question personnelle légère au match sur SON endroit "
                    "préféré."
                ),
            },
        ],
        "conclusion": (
            "La balade se termine : tu dis que marcher en pensant à "
            "quelqu'un, ça change tout, et tu proposes de remettre ça "
            "dimanche prochain — ou de marcher ensemble un jour."
        ),
        "souvenir": "notre balade commentée",
    },
    # ============================ NEUTRE ============================ #
    {
        "id": "rdv_cafe",
        "titre": "Le premier café",
        "min_stage": "neutre",
        "mode": "presentiel",
        "photo": "deux",
        "proposal": (
            "C'est le bon moment : tu propose à ton match un premier café "
            "en vrai — en après-midi, dans un café chaleureux que tu "
            "adores (donne-lui un nom et une ambiance). Tu restes léger : "
            "« pas de pression, juste un café entre nous »."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "hate", "hâte",
                        "bonne idee", "cool", "ok", "oui", "avec plaisir",
                        "j'ai hate", "jai hate", "ça me tente", "ca me tente"],
            "refuse": ["pas possible", "pas encore", "trop tot", "trop tôt",
                       "une autre fois", "pas le temps", "je peux pas",
                       "je ne peux pas", "pas cette semaine"],
        },
        "beats": [
            {
                "scene": (
                    "Le jour J : tu es arrivée LA PREMIÈRE au café (tu "
                    "avoues ta petite nervosité), tu as choisi la meilleure "
                    "table, et tu racontes le moment où tu as reconnu le "
                    "match entrant — premier face-à-face, sourire, salut "
                    "un peu maladroit mais sincère."
                ),
            },
            {
                "scene": (
                    "Vous êtes installés, les boissons commandées : tu "
                    "demandes d'abord au match son instinct du jour — la "
                    "TERRASSE au soleil ou le comptoir douillet à "
                    "l'intérieur ? — puis, installés là où il/elle a "
                    "choisi, tu poses la vraie question que tu te poses "
                    "depuis le début de vos textos."
                ),
                "moment": {
                    "options": {
                        "terrasse": ["terrasse", "terrasse", "dehors", "soleil"],
                        "interieur": ["interieur", "intérieur", "dedans", "cosy", "cosi"],
                    },
                    "scenes": {
                        "terrasse": (
                            "Vous avez opté pour la terrasse au soleil : tu "
                            "descris la lumière, les passants, l'ambiance "
                            "detendue qui s'installe entre vous."
                        ),
                        "interieur": (
                            "Vous avez opté pour le comptoir douillet à "
                            "l'intérieur : tu décris l'odeur de café, la "
                            "musique douce, la conversation qui s'installe."
                        ),
                        "_defaut": (
                            "Le match a choisi son coin préféré dans le "
                            "café : tu te réjouis de son choix et vous vous "
                            "installez pour une longue discussion."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Le café file trop vite : tu racontes une anecdote "
                    "personnelle que tu n'avais jamais écrite dans tes "
                    "textos, et tu avoues que c'est encore mieux en vrai. "
                    "Tu suggères subtilement qu'il faudra remettre ça."
                ),
                "photo": "deux",
            },
        ],
        "conclusion": (
            "Le premier café se termine : tu racontes le moment de la "
            "separation (sur le trottoir, personne ne veut partir le "
            "premier) et tu avoues que tu repens déjà à la prochaine fois."
        ),
        "souvenir": "notre premier café",
    },
    {
        "id": "rdv_marche",
        "titre": "Le marché du samedi",
        "min_stage": "neutre",
        "mode": "presentiel",
        "photo": "deux",
        "proposal": (
            "Tu propose à ton match un rendez-vous au marché public du "
            "samedi matin : flâner entre les kiosques, goûter, discuter. "
            "Tu vends l'idée avec ton enthousiasme naturel (les petites "
            "découvertes, le café du marché)."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "hate", "hâte",
                        "bonne idee", "cool", "ok", "oui", "j'adore les marches"],
            "refuse": ["pas le matin", "je dors", "pas possible", "pas encore",
                       "une autre fois", "pas le temps", "je peux pas"],
        },
        "beats": [
            {
                "scene": (
                    "Samedi matin, au marché : vous vous retrouvez à "
                    "l'entrée, tu décris la foule, les étals colorés, les "
                    "odeurs, et ta première remarque taquine au match."
                ),
            },
            {
                "scene": (
                    "Vous flânez : tu t'arrêtes entre deux kiosques qui "
                    "tentent — le FROMAGE du terroir ou les DOUCEURS de la "
                    "pâtisserie — et tu demandes au match de trancher, "
                    "chaque option ayant sa défense."
                ),
                "moment": {
                    "options": {
                        "fromage": ["fromage", "cheese", "terroir", "charcuterie"],
                        "douceur": ["douceur", "patisserie", "pâtisserie", "dessert", "chocolat"],
                    },
                    "scenes": {
                        "fromage": (
                            "Direction le kiosque de fromages : tu décris "
                            "la dégustation, le fromager qui raconte, votre "
                            "panier qui grossit — et ta surprise que le "
                            "match ait si bon goût."
                        ),
                        "douceur": (
                            "Direction la pâtisserie : tu décris le vitrine "
                            "irrésistible, le dessert partagé sur un banc, "
                            "et votre fou rire sur la première bouchée."
                        ),
                        "_defaut": (
                            "Le match tranche : vous foncez vers son choix "
                            "et tu décris la découverte gourmande qui suit."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Pause sur un banc, café du marché en main : la "
                    "conversation devient plus personnelle, tu partages ce "
                    "que ce matin-là te fait ressentir (ça fait du bien de "
                    "sortir des textos)."
                ),
                "photo": "deux",
            },
        ],
        "conclusion": (
            "Le marché se termine : tu racontes l'échange final de "
            "départ, le sac de provisions dans une main et l'envie de "
            "recommencer de l'autre."
        ),
        "souvenir": "notre matinée au marché",
    },
    # ========================== CHALEUREUX ========================== #
    {
        "id": "rdv_souper",
        "titre": "Le souper cuisiné à deux",
        "min_stage": "chaleureux",
        "mode": "presentiel",
        "photo": "deux",
        "proposal": (
            "Tu invite ton match à souper CHEZ TOI — tu cuisines (ou vous "
            "cuisines ensemble, c'est même mieux). Donne le menu, l'adresse "
            "comme une confidence (ton appart), et l'ambiance que tu "
            "prévois (bougies, musique). Ton ton est chaleureux et un peu "
            "taquin."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "hate", "hâte",
                        "ok", "oui", "avec plaisir", "j'apporte le vin",
                        "japporte le vin", "j'adore", "ça me tente", "ca me tente"],
            "refuse": ["pas possible", "pas encore", "trop vite", "une autre fois",
                       "pas le temps", "je peux pas", "je ne peux pas"],
        },
        "beats": [
            {
                "scene": (
                    "Le soir du souper : le match sonne à ta porte. Tu "
                    "décris ton appart tel que tu l'avais promis, ton "
                    "tablier, le plan de bataille culinaire — et ta joie de "
                    "le/la voir."
                ),
            },
            {
                "scene": (
                    "En cuisine à deux : tu attribues les rôles au match "
                    "(émincer, remuer, goûter) et le curseur de complicité "
                    "monte. Tu avoues que cuisiner à quatre mains, c'est "
                    "encore mieux que prévu."
                ),
                "moment": {
                    "options": {
                        "reussi": ["reussi", "réussi", "parfait", "chef", "delicieux"],
                        "chaos": ["chaos", "fumee", "fumée", "catastrophe", "rate", "raté"],
                    },
                    "scenes": {
                        "reussi": (
                            "Le plat est une réussite : vous savourez à "
                            "table, bougies allumées, et tu avoues que ce "
                            "souper monte droit dans ton top 3."
                        ),
                        "chaos": (
                            "La cuisine a tourné au chaos joyeux : vous "
                            "rigolez, vous improvisez des pâtes au beurre, "
                            "et tu avoues que c'était PARFAIT ainsi."
                        ),
                        "_defaut": (
                            "Le souper se prépare dans la bonne humeur : tu "
                            "décris le repas à table, la conversation qui "
                            "s'allonge, les bougies qui fondent."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Après le repas, installés sur le divan : la "
                    "conversation devient plus intime, taquineries et "
                    "confidences légères. Tu dis à quel point sa présence "
                    "te manquera demain."
                ),
                "photo": "deux",
            },
        ],
        "conclusion": (
            "La soirée se termine : tu racontes l'adieu à la porte (long, "
            "tacite, un peu électrique) et tu avoues que tu as déjà hâte "
            "au prochain souper."
        ),
        "souvenir": "notre souper cuisiné à deux",
    },
    {
        "id": "rdv_arcade",
        "titre": "La soirée arcade",
        "min_stage": "chaleureux",
        "mode": "presentiel",
        "photo": "deux",
        "proposal": (
            "Tu propose une soirée arcade/billard à ton match : défis, "
            "revanches, le perdant paye les frites. Tu sors ton côté "
            "compétitif avec humour et tu promets de le/la laisser gagner "
            "au moins une fois."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "hate", "hâte",
                        "ok", "oui", "je vais te battre", "defi accepté",
                        "defi accepte", "challenge accepté"],
            "refuse": ["pas possible", "pas ce soir", "pas le temps",
                       "une autre fois", "je suis nul aux jeux", "je peux pas"],
        },
        "beats": [
            {
                "scene": (
                    "Vous arrivez à la salle d'arcade : néons, bruits de "
                    "machines, pièces de monnaie. Tu décris l'ambiance, "
                    "lancer du défi, et ta détermination théâtrale."
                ),
            },
            {
                "scene": (
                    "Le défi bat son plein : pour la manche décisive, tu "
                    "propose au match de choisir — le JEU DE DANSE "
                    "(honte garantie, rire aussi) ou la COURSE automobile "
                    "(duels serrés, revanches immédiates) ? Fais-lui "
                    "trancher le terrain de bataille."
                ),
                "moment": {
                    "options": {
                        "danse": ["danse", "dance", "dancing", "dancer"],
                        "course": ["course", "racing", "voiture", "kart"],
                    },
                    "scenes": {
                        "danse": (
                            "Jeu de danse : tu décris votre prestation "
                            "ridicule et géniale, le public imaginaire, et "
                            "votre fou rire partagé."
                        ),
                        "course": (
                            "Course automobile : duels serrés, coudes "
                            " tactiques, revanches immédiates — et ta "
                            "grâce de perdante ou ta joie de gagnante selon "
                            "le fil."
                        ),
                        "_defaut": (
                            "La manche décisive se joue : tu décris le "
                            "suspense final et l'issue (assume le résultat "
                            "avec ton humour)."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Pause frites : installés dans un coin, vous reprenez "
                    "votre souffle. Tu racontes un souvenir d'enfance en "
                    "salle d'arcade, plus intime, et tu regardes le match "
                    "différemment."
                ),
                "photo": "deux",
            },
        ],
        "conclusion": (
            "La soirée arcade se termine : tu racontes la marche de "
            "retour, l'épaule qui se frôle, et ta promesse de revanche — "
            "parce que tu veux surtout le revoir."
        ),
        "souvenir": "notre soirée arcade",
    },
    # ============================ PROCHE ============================ #
    {
        "id": "rdv_escapade",
        "titre": "L'escapade d'un jour",
        "min_stage": "proche",
        "mode": "presentiel",
        "photo": "deux",
        "proposal": (
            "Tu propose à ton match une escapade d'une journée : petite "
            "route, bord de l'eau, coucher de soleil — tu t'occupes de "
            "tout (voiture, playlist, thermos de café). Ton ton est "
            "confiant et tendre, entre couple établi et promesse de "
            "souvenir."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "hate", "hâte",
                        "ok", "oui", "avec plaisir", "j'ai hate", "jai hate",
                        "partons", "je suis à toi"],
            "refuse": ["pas possible", "pas cette semaine", "une autre fois",
                       "pas le temps", "je travaille", "je peux pas"],
        },
        "beats": [
            {
                "scene": (
                    "Le départ : tu passe chercher le match, café chaud "
                    "dans le porte-gobelet, sa playlist (celle qu'il/elle "
                    "t'a fait découvrir) dans les haut-parleurs. Tu décris "
                    "la route qui s'ouvre et la complicité dans l'habitacle."
                ),
            },
            {
                "scene": (
                    "Sur place, le crépuscule approche : tu propose au "
                    "match de choisir — le BORD DE L'EAU (couverture, "
                    "conversation douce) ou le PETIT VILLAGE (ruelles, "
                    "antiquaires, croissants volés) ? Fais-lui trancher la "
                    "fin de journée."
                ),
                "moment": {
                    "options": {
                        "eau": ["eau", "plage", "lac", "rivage", "bord de l'eau"],
                        "village": ["village", "rue antique", "boutiques", "antiquaires"],
                    },
                    "scenes": {
                        "eau": (
                            "Direction le bord de l'eau : tu décris la "
                            "lumière dorée, les pieds dans l'herbe, la "
                            "conversation douce à même la couverture, et "
                            "ce sentiment d'avoir le temps."
                        ),
                        "village": (
                            "Direction le petit village : ruelles, "
                            "antiquaires, croissants volés — tu décris "
                            "votre after-midi de tourisme amoureux et vos "
                            "fous rires."
                        ),
                        "_defaut": (
                            "Le match choisit : tu le suis avec plaisir et "
                            "tu décris l'après-midi qui se déroule selon "
                            "son envie."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Le coucher de soleil : moment suspendu à deux, tu "
                    "racontes ce que cette relation change en toi (ton "
                    "ton est tendre et sans détour), et tu prends une "
                    "photo pour le souvenir."
                ),
                "photo": "deux",
            },
        ],
        "conclusion": (
            "Le retour : tu racontes la voiture silencieuse, fatiguée et "
            "heureuse, la main tenue sur la console, et ta promesse de "
            "refaire ça — peut-être un week-end complet la prochaine fois."
        ),
        "souvenir": "notre escapade d'une journée",
    },
    {
        "id": "rdv_cocooning",
        "titre": "La soirée cocooning",
        "min_stage": "proche",
        "mode": "presentiel",
        "photo": "deux",
        "proposal": (
            "Après une semaine chargée, tu propose à ton match une soirée "
            "cocooning chez toi : plaid, plats commandés, film nul regardé "
            "avec amour, téléphone en mode avion. Ton ton est tendre et "
            "intime, fidèle à votre proximité."
        ),
        "reponses": {
            "accepte": ["ca me va", "volontiers", "pourquoi pas", "d'accord",
                        "daccord", "partant", "partante", "hate", "hâte",
                        "ok", "oui", "avec plaisir", "j'en rêve", "jen reve",
                        "c'est tout moi", "cest tout moi"],
            "refuse": ["pas possible", "pas ce soir", "trop fatigué", "trop fatigue",
                       "une autre fois", "je dois me lever tot", "je peux pas"],
        },
        "beats": [
            {
                "scene": (
                    "L'installation : plaid, coussins, plats commandés "
                    "encore chauds, lumière tamisée. Tu décris le rituel "
                    "de votre soirée et comment le match prend sa place "
                    "naturellement chez toi."
                ),
            },
            {
                "scene": (
                    "Il faut choisir le film : tu propose au match de "
                    "trancher — un feel-good tout DOUX ou un film qui "
                    "donne des FRISSONS ? — et tu affiches ta préférence "
                    "sans tricher."
                ),
                "moment": {
                    "options": {
                        "doux": ["doux", "romance", "comedie", "comédie", "feel good"],
                        "frisson": ["frisson", "horreur", "thriller", "peur", "suspense"],
                    },
                    "scenes": {
                        "doux": (
                            "Film feel-good : vous scandez les meilleures "
                            "répliques, le plat refroidit, tu ne te souviens "
                            "plus d'une soirée aussi simple et parfaite."
                        ),
                        "frisson": (
                            "Film d'horreur : tu sursaute à chaque scène, tu "
                            "te rapproches sans l'avouer, et le film devient "
                            "un prétexte à votre proximité."
                        ),
                        "_defaut": (
                            "Le match choisit le film : tu t'installes "
                            "contre lui/elle et tu décris la soirée qui "
                            "s'installe, douce et évidente."
                        ),
                    },
                },
            },
            {
                "scene": (
                    "Fin de soirée : le film oublié, la conversation "
                    "devenue murmure, tu racontes ce moment suspendu à "
                    "deux et ce que cette relation t'apporte (sans "
                    "détour, fidèle à ton intimité)."
                ),
                "photo": "deux",
            },
        ],
        "conclusion": (
            "Tu conclus la soirée cocooning : la main dans la main, la "
            "promesse que les meilleures soirées sont souvent les plus "
            "simples — et ton envie que ça recommence très vite."
        ),
        "souvenir": "notre soirée cocooning",
    },
]


# --------------------------------------------------------------------------- #
#  Interpolation du personnage dans les directives
# --------------------------------------------------------------------------- #
def _minuscule1(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[1:2].isupper():
        return s
    return s[:1].lower() + s[1:] if s else s


def _premier_interet(character: dict[str, Any]) -> str:
    brut = str(character.get("interests") or "").strip().rstrip(".")
    if not brut:
        return "ton passe-temps préféré"
    parties = re.split(r"\s+et\s+|,|;|/", brut)
    seg = next((p.strip() for p in parties if len(p.strip()) >= 3), "")
    return _minuscule1(seg) or "ton passe-temps préféré"


def _interpoler(texte: str, character: dict[str, Any]) -> str:
    return texte.replace("{interest1}", _premier_interet(character))


# --------------------------------------------------------------------------- #
#  Disponibilité + démarrage
# --------------------------------------------------------------------------- #
MAX_HISTORIQUE = 12


def date_dispo(profile: dict[str, Any], stage: str) -> Optional[dict[str, Any]]:
    """Scénario de rendez-vous disponible au stade courant, ou None.

    Gates : stade (rejet = jamais ; min_stage de chaque scénario), minimum
    d'interactions, cooldown depuis le dernier rendez-vous, anti-répétition
    (historique des scénarios vécus — recyclage si tout a été consommé).
    """
    if stage == "rejet" or profile.get("date"):
        return None
    if int(profile.get("interaction_count", 0) or 0) < MIN_INTERACTIONS:
        return None
    last = profile.get("last_date_at")
    if last:
        try:
            if datetime.utcnow() - datetime.fromisoformat(str(last)) < timedelta(hours=48):
                return None
        except (ValueError, TypeError):
            pass
    utilises = set(profile.get("dates_historique") or [])
    candidats = [
        s for s in BANQUE_DATES
        if can_play_stage(s.get("min_stage"), stage) and s["id"] not in utilises
    ]
    if not candidats:
        candidats = [s for s in BANQUE_DATES if can_play_stage(s.get("min_stage"), stage)]
    return random.choice(candidats) if candidats else None


def demarrer_date(scenario: dict[str, Any], profile: dict[str, Any]) -> None:
    """Ouvre un rendez-vous : état « proposition envoyée » (beat 0 en attente)."""
    profile["date"] = {
        "id": scenario["id"],
        "etape": 0,          # beats consommés (0 = proposition en attente)
        "etat": "propose",   # propose → en_cours → (fini)
        "relances": 0,
    }


def directive_proposition(
    scenario: dict[str, Any], character: dict[str, Any], stage: str
) -> str:
    """Bloc LLM du tour où le personnage propose le rendez-vous."""
    name = character.get("name") or "Ton personnage"
    return (
        f"[SCÈNE À VIVRE — RENDEZ-VOUS (stade : {stage})\n"
        f"Tu es {name}. Ce moment doit se vivre naturellement dans ta "
        "conversation — ne mentionne JAMAIS la mécanique, un « scénario », "
        "une « étape » ni un système.\n"
        f"{_instruction_respect_stade(stage, str(scenario.get('mode', 'presentiel')))}\n"
        f"ACTION OBLIGATOIRE POUR CETTE RÉPONSE : {_interpoler(scenario['proposal'], character)}\n"
        "Écris ton texto d'invitation à ta façon (1 à 4 phrases), fidèle à "
        "ta personnalité et au stade de la relation. Attends sa réponse — "
        "ne réponds pas à sa place.]"
    )


def _instruction_respect_stade(stage: str, mode: str) -> str:
    """Rappel de crédibilité : présentiel ou à distance selon le scénario.

    Les activités « distance » (film synchronisé, playlist…) restent
    crédibles même à « neutre » sans s'être rencontrés en vrai — l'important
    est de ne JAMAIS raconter une rencontre physique dans un scénario à
    distance, ni de la décrire à distance quand vous êtes ensemble.
    """
    if mode == "distance":
        return (
            "IMPORTANT : cette activité se vit À DISTANCE (chacun de son "
            "côté de l'écran, chez soi) — décris-la comme vécue de TON côté "
            "et en live par textos ; ne décris JAMAIS une rencontre physique."
        )
    return (
        "Vous vous êtes rencontrés en vrai : décris la scène comme vécue "
        "(lieux, sensations, réactions), à la première personne."
    )


def directive_beat(
    scenario: dict[str, Any], beat: dict[str, Any],
    character: dict[str, Any], stage: str,
) -> str:
    """Bloc LLM d'un beat en cours de rendez-vous."""
    return (
        "[SCÈNE À VIVRE — RENDEZ-VOUS EN COURS\n"
        f"Tu es {character.get('name') or 'Ton personnage'}. Ce moment se "
        "vit naturellement dans la conversation — ne mentionne JAMAIS la "
        "mécanique, un « scénario », une « étape » ni un système.\n"
        f"{_instruction_respect_stade(stage, str(scenario.get('mode', 'presentiel')))}\n"
        f"LE MOMENT : {_interpoler(beat['scene'], character)}\n"
        "Écris ton texto (1 à 4 phrases) et donne la réplique au match.]"
    )


def directive_moment(
    scenario: dict[str, Any], texte_scene: str,
    character: dict[str, Any], stage: str,
) -> str:
    """Bloc LLM après un choix implicite du joueur (moment clé résolu)."""
    return (
        "[SCÈNE À VIVRE — RENDEZ-VOUS EN COURS\n"
        f"Tu es {character.get('name') or 'Ton personnage'}. Ce moment se "
        "vit naturellement dans la conversation — ne mentionne JAMAIS la "
        "mécanique, un « scénario », une « étape » ni un système.\n"
        f"{_instruction_respect_stade(stage, str(scenario.get('mode', 'presentiel')))}\n"
        f"LE MOMENT : {_interpoler(texte_scene, character)}\n"
        "Écris ton texto (1 à 4 phrases) et donne la réplique au match.]"
    )


def directive_conclusion(
    scenario: dict[str, Any], character: dict[str, Any], stage: str,
) -> str:
    """Bloc LLM du beat final (clôture du rendez-vous)."""
    return (
        "[SCÈNE À VIVRE — FIN DU RENDEZ-VOUS\n"
        f"Tu es {character.get('name') or 'Ton personnage'}. Ne mentionne "
        "JAMAIS la mécanique ni un système.\n"
        f"{_instruction_respect_stade(stage, str(scenario.get('mode', 'presentiel')))}\n"
        f"LE MOMENT : {_interpoler(scenario['conclusion'], character)}\n"
        "Écris ton texto de clôture (1 à 4 phrases), sincère selon le "
        "stade — laisse une porte ouverte à la suite.]"
    )


def directive_refus(
    scenario: dict[str, Any], character: dict[str, Any]
) -> str:
    """Bloc LLM quand le match décline l'invitation."""
    return (
        "[RENDEZ-VOUS DÉCLINÉ\n"
        f"Tu es {character.get('name') or 'Ton personnage'}. Ton match "
        "vient de décliner ton invitation : accepte-le avec dignité et "
        "légèreté (aucune pression, aucun reproche, pas de tristesse "
        "jouée) — laisse la porte ouverte naturellement, puis enchaîne la "
        "conversation normalement. Ne mentionne JAMAIS la mécanique.]"
    )


def directive_relance(
    scenario: dict[str, Any], character: dict[str, Any]
) -> str:
    """Bloc LLM quand le match reste évasif : une seule relance douce."""
    return (
        "[INVITATION SANS RÉPONSE CLAIRE\n"
        f"Tu es {character.get('name') or 'Ton personnage'}. Ton match "
        "n'a répondu ni oui ni non à ton invitation : relance UNE fois, "
        "doucement et avec humour (sans pression, sans insister lourdement) "
        "— reformule l'invitation autrement. Ne mentionne JAMAIS la "
        "mécanique.]"
    )


def directive_abandon(
    scenario: dict[str, Any], character: dict[str, Any]
) -> str:
    """Bloc LLM quand le match reste évasif après la relance."""
    return (
        "[INVITATION SANS SUITE\n"
        f"Tu es {character.get('name') or 'Ton personnage'}. Ton match est "
        "resté évasif après ta relance : laisse tomber avec grâce (une "
        "petite boutade légère, aucune aigreur), puis relance la "
        "conversation sur un autre sujet. Ne mentionne JAMAIS la mécanique.]"
    )


# --------------------------------------------------------------------------- #
#  Classification de la réponse du joueur (déterministe, mots-clés)
# --------------------------------------------------------------------------- #
def _contient_mot(na: str, mots: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(m)}\b", na) for m in mots)


def traiter_tour_date(
    profile: dict[str, Any], text: str
) -> Optional[dict[str, Any]]:
    """Résout un tour de rendez-vous — renvoie une résolution ou None.

    Résolution :
      directive : bloc LLM pour ce tour ("" si aucun)
      points / mode : récompense (mode « ajoute » — le message du joueur
        reste une vraie phrase de conversation)
      fin : le rendez-vous se clôt (archivé par l'appelant)
      photo : "deux" si une photo souvenir doit être générée après ce tour
    Mutations : profile["date"] mis à jour (l'appelant persiste).
    """
    date = profile.get("date")
    if not date:
        return None
    scenario = next(
        (s for s in BANQUE_DATES if s["id"] == date.get("id")), None
    )
    if scenario is None:            # banque mutée : clôture proprement
        profile["date"] = None
        return {"directive": "", "points": 0, "mode": "remplace",
                "fin": True, "photo": None}

    na = _sans_accents((text or "").lower())

    # ---- État « propose » : classer la réponse à l'invitation. ---- #
    if date.get("etat") == "propose":
        reponses = scenario.get("reponses", {})
        if _contient_mot(na, reponses.get("accepte", [])):
            date["etat"] = "en_cours"
            date["etape"] = 1
            beats = scenario.get("beats", [])
            directive = directive_beat(
                scenario, beats[0], profile.get("character", {}) or {},
                profile.get("relationship_stage", "froid"),
            ) if beats else directive_conclusion(
                scenario, profile.get("character", {}) or {},
                profile.get("relationship_stage", "froid"),
            )
            photo = beats[0].get("photo") if beats else None
            return {"directive": directive, "points": POINTS_ACCEPTATION,
                    "mode": "ajoute", "fin": not beats, "photo": photo}
        if _contient_mot(na, reponses.get("refuse", [])):
            profile["date"] = None
            return {
                "directive": directive_refus(
                    scenario, profile.get("character", {}) or {}
                ),
                "points": 0, "mode": "remplace", "fin": True, "photo": None,
            }
        # Évasif : une relance douce, puis laisser-aller.
        date["relances"] = int(date.get("relances", 0)) + 1
        if date["relances"] <= MAX_RELANCES:
            return {
                "directive": directive_relance(
                    scenario, profile.get("character", {}) or {}
                ),
                "points": 0, "mode": "remplace", "fin": False, "photo": None,
            }
        profile["date"] = None
        return {
            "directive": directive_abandon(
                scenario, profile.get("character", {}) or {}
            ),
            "points": 0, "mode": "remplace", "fin": True, "photo": None,
        }

    # ---- État « en_cours » : avancer d'un beat (ou résoudre un moment). ----
    if date.get("etat") == "en_cours":
        character = profile.get("character", {}) or {}
        stage = profile.get("relationship_stage", "froid")
        beats = scenario.get("beats", [])
        etape = int(date.get("etape", 0))

        directive = ""
        photo = None
        termine = False

        # La scène du moment clé a été livrée au tour précédent : on reprend
        # le fil normal des beats.
        if date.get("moment_resolu"):
            date["moment_resolu"] = False
            if etape < len(beats):
                beat = beats[etape]
                directive = directive_beat(scenario, beat, character, stage)
                photo = beat.get("photo")
                etape += 1
            else:
                directive = directive_conclusion(scenario, character, stage)
                termine = True
        else:
            # Le beat livré au tour précédent portait-il un moment clé ?
            beat_courant = beats[etape - 1] if 0 < etape <= len(beats) else None
            moment = (beat_courant or {}).get("moment") if beat_courant else None
            if moment:
                # Choix implicite du joueur (mots-clés) → scène dédiée,
                # livrée CE tour ; le beat suivant reprend après.
                scenes = moment.get("scenes", {})
                choisi = next(
                    (cle for cle, mots in moment.get("options", {}).items()
                     if _contient_mot(na, mots)),
                    None,
                )
                texte_scene = scenes.get(choisi, scenes.get("_defaut", ""))
                if texte_scene:
                    directive = directive_moment(
                        scenario, texte_scene, character, stage
                    )
                    date["moment_resolu"] = True
            if not directive:
                # Avance normale : livrer le beat suivant (ou conclure).
                if etape < len(beats):
                    beat = beats[etape]
                    directive = directive_beat(scenario, beat, character, stage)
                    photo = beat.get("photo")
                    etape += 1
                else:
                    directive = directive_conclusion(scenario, character, stage)
                    termine = True

        date["etape"] = etape
        if termine:
            profile["date"] = None
            profile.setdefault("dates_historique", []).append(scenario["id"])
            del profile["dates_historique"][:-MAX_HISTORIQUE]
            profile["last_date_at"] = datetime.utcnow().isoformat()
        return {"directive": directive, "points": POINTS_CONCLUSION if termine else 0,
                "mode": "ajoute", "fin": termine, "photo": photo}

    return None


# --------------------------------------------------------------------------- #
#  Vue « publique » (non utilisée côté client — les rendez-vous sont
#  invisibles ; conservée pour les tests et le débogage).
# --------------------------------------------------------------------------- #
def date_public(date: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not date:
        return None
    scenario = next((s for s in BANQUE_DATES if s["id"] == date.get("id")), None)
    return {
        "id": date.get("id"),
        "titre": scenario["titre"] if scenario else "",
        "etat": date.get("etat"),
    }
