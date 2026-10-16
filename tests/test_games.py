# Tests des mini-jeux de conversation — miroir de server/relation/games.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.relation import games as G  # noqa: E402
from server.relation.stages import STAGE_ORDER  # noqa: E402


def _profil(character=None, stage="neutre", score=500):
    """Profil de session minimal pour le moteur de jeux."""
    return {
        "meta": {"user": "test", "session_id": "abc123", "titre": "Test"},
        "character": character or {},
        "relationship_score": score,
        "relationship_stage": stage,
        "games_historique": [],
        "game": None,
    }


PERSONNAGE_RICHE = {
    "name": "Camille Desrosiers",
    "age": "27",
    "gender": "F",
    "interests": "L'escalade de bloc en salle et la lecture de romans policiers",
    "occupation": "Avocate en droit de l'environnement pour une ONG",
}


class TestGatesDeStade:
    def test_aucun_jeu_au_rejet(self):
        for gtype in G.JEUX_DISPONIBLES:
            jeu, message = G.demarrer_jeu(gtype, _profil(stage="rejet"), "rejet")
            assert jeu is None
            assert message and "Rejet" in message

    def test_deux_verites_du_neutre(self):
        # Rien avant « neutre » : à froid, on discute simplement.
        jeu, message = G.demarrer_jeu(
            G.TYPE_DEUX_VERITES, _profil(PERSONNAGE_RICHE, "froid"), "froid"
        )
        assert jeu is None and "Neutre" in message
        jeu, _ = G.demarrer_jeu(
            G.TYPE_DEUX_VERITES, _profil(PERSONNAGE_RICHE, "neutre"), "neutre"
        )
        assert jeu is not None

    def test_vingt_questions_du_neutre(self):
        jeu, message = G.demarrer_jeu(
            G.TYPE_VINGT_QUESTIONS, _profil(PERSONNAGE_RICHE, "froid"), "froid"
        )
        assert jeu is None and "Neutre" in message
        jeu, _ = G.demarrer_jeu(
            G.TYPE_VINGT_QUESTIONS, _profil(PERSONNAGE_RICHE, "neutre"), "neutre"
        )
        assert jeu is not None

    def test_action_verite_du_neutre(self):
        jeu, message = G.demarrer_jeu(
            G.TYPE_ACTION_VERITE, _profil(stage="froid"), "froid"
        )
        assert jeu is None and "Neutre" in message
        jeu, message = G.demarrer_jeu(
            G.TYPE_ACTION_VERITE, _profil(stage="reserve"), "reserve"
        )
        assert jeu is None and "Neutre" in message
        jeu, _ = G.demarrer_jeu(
            G.TYPE_ACTION_VERITE, _profil(stage="neutre"), "neutre"
        )
        assert jeu is not None

    def test_gates_cohérentes_sur_tous_les_stades(self):
        for gtype, info in G.JEUX_DISPONIBLES.items():
            for st in STAGE_ORDER:
                profil = _profil(PERSONNAGE_RICHE, st)
                jeu, message = G.demarrer_jeu(gtype, profil, st)
                if st == "rejet" or STAGE_ORDER.index(st) < STAGE_ORDER.index(
                    info["min_stage"]
                ):
                    assert jeu is None, f"{gtype} ne devrait pas démarrer à {st}"
                else:
                    # 2V1M requiert de la matière : le personnage riche en a.
                    assert jeu is not None, f"{gtype} devrait démarrer à {st}"

    def test_jeu_inconnu(self):
        jeu, message = G.demarrer_jeu("poker", _profil(), "neutre")
        assert jeu is None and "inconnu" in message.lower()

    def test_jeu_deja_en_cours(self):
        profil = _profil(PERSONNAGE_RICHE, "neutre")
        jeu, _ = G.demarrer_jeu(G.TYPE_VINGT_QUESTIONS, profil, "neutre")
        assert jeu is not None
        profil["game"] = jeu
        jeu2, message = G.demarrer_jeu(
            G.TYPE_DEUX_VERITES, profil, "neutre"
        )
        assert jeu2 is None and "déjà" in message


class TestDeuxVeritesUnMensonge:
    def _demarrer(self, stage="neutre"):
        profil = _profil(PERSONNAGE_RICHE, stage)
        jeu, ouverture = G.demarrer_jeu(G.TYPE_DEUX_VERITES, profil, stage)
        assert jeu is not None
        profil["game"] = jeu
        return profil, jeu, ouverture

    def test_trois_enonces_avec_ouverture_numerotee(self):
        profil, jeu, ouverture = self._demarrer()
        assert len(jeu["enonces"]) == 3
        assert 1 <= jeu["mensonge"] <= 3
        assert "1️⃣" in ouverture and "2️⃣" in ouverture and "3️⃣" in ouverture
        # Le mensonge fait partie des énoncés affichés.
        assert jeu["enonces"][jeu["mensonge"] - 1]

    def test_les_deux_vraies_statements_verifiables(self):
        """Chaque énoncé non-mensonge est dérivé de la fiche visible."""
        profil, jeu, _ = self._demarrer()
        enonces = list(jeu["enonces"])
        mensonge = enonces.pop(jeu["mensonge"] - 1)  # numéro joueur 1-3
        joined = " ".join(enonces)
        # Au moins un énoncé vrai parle d'âge / intérêts / métier.
        assert any(
            fragment in joined
            for fragment in ("27 ans", "escalade de bloc", "lecture", "Côté travail")
        )
        assert mensonge  # le faux existe bien

    def test_devine_le_mensonge_gagne_puis_manche_2(self):
        profil, jeu, _ = self._demarrer()
        res = G.traiter_message_jeu(profil, f"c'est le {jeu['mensonge']}", "neutre")
        assert res is not None
        assert res["points"] == G.POINTS_2V1M_GAGNE
        assert res["mode"] == "remplace"
        # La manche 2 est ouverte (à vous de piéger) — le jeu continue.
        assert res["fin"] is False
        assert jeu["step"] == "inverse"
        assert "BON" in res["directive"] or "GAGN" in res["directive"]
        assert "MANCHE 2" in res["directive"]
        # La directive cite l'énoncé mensonger : le LLM peut révéler.
        assert jeu["enonces"][jeu["mensonge"] - 1] in res["directive"]

        # Manche 2 : le joueur envoie ses énoncés → le personnage devine.
        res2 = G.traiter_message_jeu(
            profil, "1. j'ai un chat\n2. j'ai un chien\n3. j'ai un hamster", "froid"
        )
        assert res2 is not None and res2["fin"] is False
        assert jeu["step"] == "inverse_devine"
        assert "devine" in res2["directive"].lower()
        public = G.jeu_public(jeu)
        assert public["label"] and public["chips"] == []

        # La révélation clôt la manche 2 avec un bonus de participation.
        res3 = G.traiter_message_jeu(profil, "bravo c'est ça !", "neutre")
        assert res3 is not None
        assert res3["points"] == G.POINTS_2V1M_MANCHE2
        assert res3["mode"] == "ajoute" and res3["fin"] is True
        assert profil["game"] is None

    def test_devine_faux_perdu_puis_manche_2(self):
        profil, jeu, _ = self._demarrer()
        mauvais = [n for n in (1, 2, 3) if n != jeu["mensonge"]][0]
        res = G.traiter_message_jeu(profil, f"le {mauvais}", "neutre")
        assert res is not None
        assert res["points"] == G.POINTS_2V1M_PERDU
        assert res["fin"] is False and jeu["step"] == "inverse"
        assert "TROMP" in res["directive"]
        # La manche 2 peut être passée (« pas maintenant »).
        res2 = G.traiter_message_jeu(profil, "pas maintenant 😅", "neutre")
        assert res2 is not None and res2["fin"] is True
        assert profil["game"] is None

    def test_mots_chiffres_detectes(self):
        profil, jeu, _ = self._demarrer()
        mot = {1: "un", 2: "deux", 3: "trois"}[jeu["mensonge"]]
        res = G.traiter_message_jeu(profil, f"je dis {mot}", "neutre")
        assert res is not None and res["points"] == G.POINTS_2V1M_GAGNE
        assert jeu["step"] == "inverse"

    def test_ouverture_jeu_de_l_app(self):
        """Le jeu est présenté comme une fonctionnalité de l'application."""
        for stage in ("neutre", "chaleureux", "proche"):
            _, _, ouverture = self._demarrer(stage)
            assert "app" in ouverture.lower()

    def test_babillage_n_est_pas_une_devinette(self):
        profil, jeu, _ = self._demarrer()
        res = G.traiter_message_jeu(profil, "j'ai un truc en tête aussi 😄", "neutre")
        assert res is None
        assert profil["game"] is not None  # le jeu continue

    def test_abandon_silencieux_apres_3_messages_hors_jeu(self):
        profil, jeu, _ = self._demarrer()
        for i in range(G.MAX_INACTIF):
            res = G.traiter_message_jeu(profil, "bla bla bla", "neutre")
        assert res is not None and res["fin"] is True
        assert res["points"] == 0 and profil["game"] is None

    def test_vie_publique_sans_secret(self):
        profil, jeu, _ = self._demarrer()
        public = G.jeu_public(jeu)
        assert public is not None
        assert set(public.keys()) == {"type", "label", "chips"}
        assert public["chips"] == ["1", "2", "3"]
        assert public["label"] == "Jeu - devine le mensonge !"
        assert "mensonge" not in public

    def test_enonces_varies_entre_parties(self):
        """Anti-répétition : deux parties successives ne proposent pas les
        mêmes énoncés tant qu'il reste des formulations inutilisées."""
        profil = _profil(PERSONNAGE_RICHE, "neutre")
        enonces_vus: list[frozenset[str]] = []
        for _ in range(3):
            jeu, _ = G.demarrer_jeu(G.TYPE_DEUX_VERITES, profil, "neutre")
            assert jeu is not None
            courant = frozenset(jeu["enonces"])
            assert courant not in enonces_vus, "énoncés répétés à partie suivante"
            enonces_vus.append(courant)
            # Clôt la partie (devine le bon mensonge + passe la manche 2).
            profil["game"] = jeu
            G.traiter_message_jeu(profil, f"c'est le {jeu['mensonge']}", "neutre")
            G.traiter_message_jeu(profil, "pas maintenant", "neutre")


class TestActionOuVerite:
    def _demarrer(self, stage="neutre"):
        profil = _profil(PERSONNAGE_RICHE, stage)
        jeu, ouverture = G.demarrer_jeu(G.TYPE_ACTION_VERITE, profil, stage)
        assert jeu is not None
        profil["game"] = jeu
        return profil, jeu, ouverture

    def test_ouverture_demande_le_choix(self):
        _, _, ouverture = self._demarrer()
        assert "action ou vérité" in ouverture.lower()

    def test_choix_action_propose_un_defi(self):
        profil, jeu, _ = self._demarrer()
        res = G.traiter_message_jeu(profil, "action", "neutre")
        assert res is not None
        assert res["points"] == 0 and res["fin"] is False
        assert jeu["step"] == "reponse" and jeu["invite"]
        assert "DÉFI" in res["directive"] and jeu["invite"] in res["directive"]

    def test_choix_verite_avec_puce_client(self):
        """La puce « Vérité » (accentué) passe la détection sans accents."""
        profil, jeu, _ = self._demarrer()
        res = G.traiter_message_jeu(profil, "Vérité", "neutre")
        assert res is not None
        assert jeu["step"] == "reponse"
        assert "VÉRITÉ" in res["directive"]

    def test_invites_respectent_le_stade(self):
        """Aucune invite trop intime proposée sous son stade (20 tirages)."""
        for stage in ("neutre", "chaleureux", "proche"):
            profil, jeu, _ = self._demarrer(stage)
            for i in range(20):
                profil["game"] = {"type": "action_verite", "step": "choix",
                                  "invite": None, "inactif": 0}
                res = G.traiter_message_jeu(
                    profil, "vérité" if i % 2 else "action", stage
                )
                assert res is not None and profil["game"]["invite"]
                # L'invite tirée est une banque du stade (substitution du
                # premier intérêt du personnage appliquée).
                interets = G._segments_interets(PERSONNAGE_RICHE)
                i1 = interets[0] if interets else "ton passe-temps préféré"
                textes = {
                    b["texte"].replace("{interest1}", i1)
                    for b in G.BANQUE_VERITES + G.BANQUE_ACTIONS
                }
                assert profil["game"]["invite"] in textes

    def test_reponse_clot_avec_participation(self):
        profil, jeu, _ = self._demarrer()
        G.traiter_message_jeu(profil, "vérité", "neutre")
        res = G.traiter_message_jeu(profil, "mon pire rendez-vous c'était…", "neutre")
        assert res is not None
        assert res["points"] == G.POINTS_AOV_PARTICIPATION
        assert res["mode"] == "ajoute" and res["fin"] is True
        assert profil["game"] is None

    def test_puces_client_choix(self):
        profil, jeu, _ = self._demarrer()
        public = G.jeu_public(jeu)
        assert public["chips"] == ["Action", "Vérité"]
        # Après choix : plus de puces (réponse libre), toujours sans secret.
        G.traiter_message_jeu(profil, "action", "neutre")
        public = G.jeu_public(jeu)
        assert public["chips"] == []


class TestVingtQuestions:
    def _demarrer(self, character=PERSONNAGE_RICHE, stage="neutre"):
        profil = _profil(character, stage)
        jeu, ouverture = G.demarrer_jeu(G.TYPE_VINGT_QUESTIONS, profil, stage)
        assert jeu is not None
        profil["game"] = jeu
        return profil, jeu, ouverture

    def test_ouverture_annonces_20_questions(self):
        _, _, ouverture = self._demarrer()
        assert "20" in ouverture and "?" not in ouverture.split("20 questions")[0][:5]

    def test_secret_lie_aux_interets_quand_possible(self):
        """Un personnage « escalade » reçoit un secret d'un domaine proche."""
        perso = {
            "name": "Maya",
            "age": "34",
            "gender": "F",
            "interests": "L'escalade de bloc en salle et la lecture",
        }
        for _ in range(20):
            profil = _profil(perso, "neutre")
            jeu, _ = G.demarrer_jeu(G.TYPE_VINGT_QUESTIONS, profil, "neutre")
            secret = G._secret_par_id(jeu["secret_id"])
            domaines_perso = G._mots_interets(perso)
            lie = bool(domaines_perso & set(secret["domaines"]))
            if lie:
                break
        assert lie, "le secret devrait être lié aux intérêts du personnage"

    def test_question_comptee_et_directive_regles(self):
        profil, jeu, _ = self._demarrer()
        res = G.traiter_message_jeu(profil, "Est-ce que ça se mange ?", "neutre")
        assert res is not None and res["fin"] is False
        assert jeu["questions"] == 1
        assert "oui / non / parfois" in res["directive"]
        # Le LLM DOIT connaître l'objet pour répondre oui/non : le nom est
        # dans la directive (côté serveur uniquement, jamais au client).
        secret = G._secret_par_id(jeu["secret_id"])
        assert secret["nom"] in res["directive"]

    def test_victoire_par_mot_cle(self):
        profil, jeu, _ = self._demarrer()
        secret = G._secret_par_id(jeu["secret_id"])
        devinette = f"je pense que c'est {secret['mots'][0]} ?"
        res = G.traiter_message_jeu(profil, devinette, "neutre")
        assert res is not None
        assert res["points"] == G.POINTS_20Q_GAGNE and res["fin"] is True
        assert profil["game"] is None
        assert secret["nom"] in res["directive"]

    def test_mot_cle_dans_un_long_message_ne_gagne_pas(self):
        """« J'adore le café, et toi sinon quoi de neuf… » n'est pas une
        devinette (message trop long)."""
        perso = dict(PERSONNAGE_RICHE)
        profil, jeu, _ = self._demarrer(perso)
        # Force un secret connu à mot unique.
        secret = next(s for s in G.BANQUE_SECRETS if s["id"] == "parapluie")
        jeu["secret_id"] = secret["id"]
        long_msg = (
            "hier j'ai marché sous la pluie sans parapluie pendant des heures, "
            "j'étais trempé de la tête aux pieds, franchement quelle journée, "
            "bref tu fais quoi de beau ces jours-ci dis-moi tout"
        )
        assert len(long_msg) > 80
        res = G.traiter_message_jeu(profil, long_msg, "neutre")
        assert res is None or res["points"] != G.POINTS_20Q_GAGNE

    def test_indice_aux_questions_5_10_15(self):
        profil, jeu, _ = self._demarrer()
        secret = G._secret_par_id(jeu["secret_id"])
        for n in range(1, 6):
            res = G.traiter_message_jeu(profil, f"question numéro {n} ?", "neutre")
        assert res is not None
        assert jeu["questions"] == 5
        assert jeu["indices_donnes"] == 1
        assert secret["indices"][0] in res["directive"]

    def test_plafond_20_questions_cloture(self):
        profil, jeu, _ = self._demarrer()
        res = None
        for _ in range(jeu["max"]):
            res = G.traiter_message_jeu(profil, "et là, ça se mange ?", "neutre")
            if res and res["fin"]:
                break
        assert res is not None and res["fin"] is True
        assert res["points"] == G.POINTS_20Q_PERDU
        assert profil["game"] is None
        secret = G._secret_par_id(jeu["secret_id"])
        assert secret["nom"] in res["directive"]

    def test_abandon_par_le_joueur(self):
        profil, jeu, _ = self._demarrer()
        res = G.traiter_message_jeu(profil, "J'abandonne 🛑", "neutre")
        assert res is not None and res["fin"] is True and res["points"] == 0
        secret = G._secret_par_id(jeu["secret_id"])
        assert secret["nom"] in res["directive"]

    def test_babillage_ne_compte_pas_comme_question(self):
        profil, jeu, _ = self._demarrer()
        for _ in range(2):
            G.traiter_message_jeu(profil, "hihi", "neutre")
        assert jeu["questions"] == 0
        # 3e message hors-jeu → abandon silencieux.
        res = G.traiter_message_jeu(profil, "hihi", "neutre")
        assert res is not None and res["fin"] is True


class TestJeuPublicSansSecret:
    def test_aucune_fuite_d_etat_interne(self):
        profil = _profil(PERSONNAGE_RICHE, "neutre")
        for gtype in (G.TYPE_DEUX_VERITES, G.TYPE_VINGT_QUESTIONS):
            jeu, _ = G.demarrer_jeu(gtype, profil, "neutre")
            assert jeu is not None
            public = G.jeu_public(jeu)
            assert public is not None
            assert set(public.keys()) == {"type", "label", "chips"}
            for cle_interdite in ("mensonge", "secret_id", "enonces", "indices"):
                assert cle_interdite not in public
        assert G.jeu_public(None) is None


class TestMultiplicateur:
    def test_miroir_du_bareme_scoring(self):
        assert G.appliquer_multiplicateur(12, 1.0) == 12
        assert G.appliquer_multiplicateur(12, 1.5) == 18
        assert G.appliquer_multiplicateur(4, 1.5) == 6
        assert G.appliquer_multiplicateur(14, 1.5) == 21
        assert G.appliquer_multiplicateur(6, 0) == 0


class TestIntegrationPromptBuilder:
    def test_directive_de_jeu_injectee(self):
        from server.config import get_config
        from server.llm.prompt_builder import PromptBuilder

        profil = _profil(PERSONNAGE_RICHE, "neutre")
        jeu, _ = G.demarrer_jeu(G.TYPE_DEUX_VERITES, profil, "neutre")
        assert jeu is not None
        directive = G.directive_en_cours(jeu, PERSONNAGE_RICHE)
        assert "NE" in directive and "RÉVÈLE JAMAIS" in directive

        pb = PromptBuilder(get_config())
        texte = pb.build_system_message(profil, [], None, game_directive=directive)
        assert directive in texte
        # Sans directive : absente.
        texte_sans = pb.build_system_message(profil, [], None)
        assert "MINI-JEU" not in texte_sans

    def test_directive_en_cours_par_jeu(self):
        profil = _profil(PERSONNAGE_RICHE, "neutre")
        jeu_aov, _ = G.demarrer_jeu(G.TYPE_ACTION_VERITE, profil, "neutre")
        assert jeu_aov is not None
        d = G.directive_en_cours(jeu_aov, PERSONNAGE_RICHE)
        assert "action ou vérité" in d.lower()
        # Après choix : la directive cite l'invite.
        profil["game"] = jeu_aov
        G.traiter_message_jeu(profil, "action", "neutre")
        d2 = G.directive_en_cours(jeu_aov, PERSONNAGE_RICHE)
        assert jeu_aov["invite"] in d2
