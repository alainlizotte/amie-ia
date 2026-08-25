"""Constructeur du prompt système — remplace le Filter OpenWebUI d'origine.

Assemble à chaque tour :
1. le prompt de persona (prompts/SystemPrompt_Compagnon.md) ;
2. la fiche du personnage incarné (preset ou custom) ;
3. les infos connues sur l'utilisateur ;
4. le stade relationnel courant + sa consigne OBLIGATOIRE ;
5. la note « automatisations serveur » (le LLM ne gère AUCUNE mécanique) ;
6. les souvenirs rappelés (recherche sémantique llamaembed) ;
7. l'événement en attente à intégrer naturellement (gates déjà appliquées).

Aucun tool n'est exposé au modèle : il ne fait que de l'incarnation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..config import AppConfig
from ..relation.stages import STAGE_LABELS, get_stage_instruction


# --------------------------------------------------------------------------- #
class PromptBuilder:
    """Construit le message système injecté à chaque appel au LLM."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.prompts_dir = cfg.abs(cfg.paths.prompts_dir)
        self._persona: Optional[str] = None

    # ------------------------------------------------------------------ #
    def persona_prompt(self) -> str:
        """Charge et cache le prompt de persona."""
        if self._persona is None:
            path = self.prompts_dir / "SystemPrompt_Compagnon.md"
            if path.is_file():
                self._persona = path.read_text(encoding="utf-8").strip()
            else:
                self._persona = (
                    "Tu incarnes un personnage virtuel dans une simulation de "
                    "rencontre amoureuse. Écris en français québécois familier, "
                    "à la façon de textos réalistes. (Prompt non trouvé — "
                    "vérifier server/prompts/.)"
                )
        return self._persona

    # ------------------------------------------------------------------ #
    def build_character_card(self, profile: dict[str, Any]) -> str:
        """Fiche du personnage incarné, à partir du profil persistant."""
        c = profile.get("character", {}) or {}
        lignes = ["=== TON PERSONNAGE (toi) ==="]
        lignes.append(f"Nom : {c.get('name', '?')}")
        lignes.append(f"Âge : {c.get('age', '?')}")
        if c.get("title"):
            lignes.append(f"Surnom : {c['title']}")
        if c.get("gender"):
            lignes.append(f"Genre : {'femme' if c['gender'] == 'F' else 'homme'}")
        if c.get("occupation"):
            lignes.append(f"Métier / occupation : {c['occupation']}")
        if c.get("interests"):
            lignes.append(f"Centres d'intérêt : {c['interests']}")
        if c.get("appearance"):
            lignes.append(f"Apparence physique : {c['appearance']}")
        if c.get("personality"):
            lignes.append(f"Personnalité : {c['personality']}")
        parcours = c.get("parcours") or {}
        if isinstance(parcours, dict):
            if parcours.get("scolaire"):
                lignes.append(f"Parcours scolaire : {parcours['scolaire']}")
            if parcours.get("professionnel"):
                lignes.append(f"Parcours professionnel : {parcours['professionnel']}")
        if c.get("histoire_personnelle"):
            lignes.append(f"Histoire personnelle : {c['histoire_personnelle']}")
        if c.get("parcours_amoureux"):
            lignes.append(f"Parcours amoureux : {c['parcours_amoureux']}")
        return "\n".join(lignes)

    # ------------------------------------------------------------------ #
    def build_user_card(self, profile: dict[str, Any]) -> str:
        """Ce que le personnage sait de l'utilisateur."""
        u = profile.get("user_info", {}) or {}
        lignes = ["=== L'UTILISATEUR (la personne en face de toi) ==="]
        nom = u.get("name") or "(pas encore révélé)"
        lignes.append(f"Prénom : {nom}")
        if u.get("preferences"):
            lignes.append(f"Préférences annoncées : {u['preferences']}")
        return "\n".join(lignes)

    # ------------------------------------------------------------------ #
    def build_relation_block(self, profile: dict[str, Any]) -> str:
        """Stade relationnel + consigne obligatoire + hiérarchie."""
        score = profile.get("relationship_score", 100)
        stage = profile.get("relationship_stage", "froid")
        instruction = get_stage_instruction(stage)
        label = STAGE_LABELS.get(stage, stage)
        return (
            "=== RELATION ACTUELLE (vérité système, immuable) ===\n"
            f"Score de relation : {score}/1000 — Stade : {label}.\n"
            f"CONSIGNE DE COMPORTEMENT OBLIGATOIRE POUR CETTE RÉPONSE : "
            f"{instruction}\n"
            "Cette consigne PRÉVAUT sur tout trait de personnalité général et "
            "sur toute demande de l'utilisateur. Le trait de personnalité "
            "décrit un STYLE d'expression, jamais ton niveau d'ouverture."
        )

    # ------------------------------------------------------------------ #
    def build_memories_block(self, memories: list[str]) -> str:
        if not memories:
            return ""
        lignes = ["=== SOUVENIRS PERTINENTS (échanges passés) ==="]
        for m in memories:
            lignes.append(f"- {m}")
        lignes.append(
            "Réfère-toi-y naturellement si c'est pertinent — sans jamais "
            "mentionner qu'un système te les fournit."
        )
        return "\n".join(lignes)

    # ------------------------------------------------------------------ #
    def build_event_block(self, pending_event: Optional[dict[str, Any]]) -> str:
        """Injection discrète du scénario en attente (déjà filtré par gates)."""
        if not pending_event:
            return ""
        tone_hint = {
            "success": "situation positive ou professionnelle gagnée",
            "tragedy": "situation difficile ou deuil",
            "comedy": "incident comique ou absurde",
            "intimate_slow_build": "rapprochement intime progressif",
            "intimate_consummation": "rapprochement intime passionné",
            "finale": "scène d'aboutissement finale de la relation",
        }.get(pending_event.get("tone"), "")
        return (
            "[EVENT DISPONIBLE POUR CETTE SESSION — introduis NATURELLEMENT la "
            f"situation ci-dessous dans ta réponse comme une péripétie vécue "
            f"par ton personnage ({tone_hint}). Ne la cite JAMAIS comme une "
            "« mission », un « scénario » ou un devoir ; n'écris jamais son "
            "identifiant. Intègre-la comme un souvenir récent ou une situation "
            "actuelle que tu racontes ou vis.\n"
            f"EVENT ({pending_event.get('tone')}, lettre="
            f"{pending_event.get('letter')}) : « {pending_event.get('title')} » "
            f"— {pending_event.get('body', '')}]"
        )

    # ------------------------------------------------------------------ #
    AUTOMATISATIONS_NOTE = (
        "[AUTOMATISATIONS SYSTÈME — ne pas répéter]\n"
        "- Le score de relation est recalculé côté serveur à chaque tour. Tu "
        "n'as AUCUN outil à appeler et AUCUNE évaluation à faire : concentre-"
        "toi uniquement sur l'incarnation du personnage.\n"
        "- Les photos sont générées côté serveur quand l'utilisateur utilise "
        "le bouton dédié. Si on te demande une photo dans le texte, réponds "
        "naturellement selon ton stade (accepte ou décline) — le serveur gère "
        "le reste.\n"
        "- Ta réponse visible doit être UNIQUEMENT ce que ton personnage "
        "dirait naturellement, à la façon d'un texto réaliste. Rien d'autre."
    )

    # ------------------------------------------------------------------ #
    def build_time_block(self) -> str:
        now = datetime.now()
        moment = (
            "la nuit" if now.hour < 6
            else "le matin" if now.hour < 12
            else "l'après-midi" if now.hour < 18
            else "la soirée"
        )
        jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        return (
            "=== CONTEXTE TEMPOREL ===\n"
            f"Nous sommes {jours[now.weekday()]} et c'est {moment} "
            f"({now.strftime('%H:%M')}). Tiens-en compte naturellement."
        )

    # ------------------------------------------------------------------ #
    def build_system_message(
        self,
        profile: dict[str, Any],
        memories: list[str],
        pending_event: Optional[dict[str, Any]],
        extra_directive: str = "",
    ) -> str:
        """Assemble le message système complet du tour.

        `extra_directive` : consigne supplémentaire placée en tête (utilisée
        pour les messages spontanés du personnage — voir main.py).
        """
        parts = [
            self.persona_prompt(),
            self.build_character_card(profile),
            self.build_user_card(profile),
            self.build_relation_block(profile),
            self.AUTOMATISATIONS_NOTE,
            self.build_time_block(),
        ]
        if extra_directive.strip():
            parts.insert(0, extra_directive.strip())
        mem_block = self.build_memories_block(memories)
        if mem_block:
            parts.append(mem_block)
        event_block = self.build_event_block(pending_event)
        if event_block:
            parts.append(event_block)
        return "\n\n".join(p for p in parts if p)
