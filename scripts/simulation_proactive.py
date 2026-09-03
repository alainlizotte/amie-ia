"""Simulation des messages proactifs « 24 h de silence » — session réelle ef0547fb61.

Travaille sur une COPIE TEMPORAIRE des données réelles (aucune écriture dans
server/data). Deux scénarios :

A. Rejeu des modes de défaillance observés en production (LLM factice) :
   1. écho exact du dernier message du personnage ;
   2. écho + fuite d'instructions (« [Current State: …] », « [Goal: …] ») ;
   3. paraphrase du dernier message (cas du 28 août) ;
   4. fuite d'analyse seule (« **Analyse de la situation:** … »).
   → aucun de ces textes ne doit atteindre l'historique persisté.

B. Génération réelle via le backend llamacpp (port hôte 8082), puis envoi
   complet (_proactive_for_session) : le message écrit par Joannie après 25 h
   de silence simulées doit être propre (ni écho, ni paraphrase, ni fuite).

Usage :
    python scripts/simulation_proactive.py            # scénarios A + B
    python scripts/simulation_proactive.py --replay   # A seul (rapide)
"""

import asyncio
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SID = "ef0547fb61"
SILENCE_H = 25

REPLAY_ONLY = "--replay" in sys.argv

# --- 1. Copie temporaire des données réelles + config dédiée ------------- #
TMP = Path(tempfile.mkdtemp(prefix="amie_simul_"))
(TMP / "data").mkdir(parents=True)
for f in (f"chat_{SID}.json", f"session_{SID}.json"):
    shutil.copy(ROOT / "server" / "data" / f, TMP / "data" / f)

llm_url = "http://127.0.0.1:8082/v1"
llm_model = "gemma-4-E4B-it-qat-q4_0-unquantized-heretic-Q4_0"

(TMP / "config.yaml").write_text(
    f"""
llm:
  backend: llamacpp
  base_url: "{llm_url}"
  model: "{llm_model}"
  think: false
  unload_after_turn: false
  temperature: 0.75
  top_p: 0.9
  max_tokens: 4096
memory:
  enabled: false
image:
  enabled: false
relation:
  proactive_enabled: true
paths:
  data_dir: {(TMP / 'data').as_posix()}
  prompts_dir: {(ROOT / 'server' / 'prompts').as_posix()}
""",
    encoding="utf-8",
)

import os  # noqa: E402

# Console Windows (cp1252) : sorties UTF-8 sans crash sur les emojis.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["AMIE_CONFIG"] = str(TMP / "config.yaml")
sys.path.insert(0, str(ROOT))

from server import main as M  # noqa: E402
from server.config import get_config  # noqa: E402
from server.llm.client import LLMClient  # noqa: E402
from server.llm.prompt_builder import PromptBuilder  # noqa: E402

CFG = get_config()


def reset_etat():
    """Remet l'historique d'origine et simule 25 h de silence."""
    shutil.copy(ROOT / "server" / "data" / f"chat_{SID}.json", TMP / "data" / f"chat_{SID}.json")
    st = M._state(SID)
    profile = st.load()
    profile["last_interaction"] = (datetime.utcnow() - timedelta(hours=SILENCE_H)).isoformat()
    profile["last_proactive_at"] = (datetime.utcnow() - timedelta(hours=SILENCE_H + 1)).isoformat()
    profile["unanswered_messages"] = 0
    st.save(profile)
    return M.ChatHistory(SID)


def dernier_message_assistant(hist):
    for m in reversed(hist.history):
        if m.role == "assistant":
            return m.content
    return ""


class LLMFactice:
    """LLM scripté : renvoie le contenu i-ème à chaque appel."""

    def __init__(self, contenus):
        self.contenus = contenus
        self.appels = 0

    async def chat(self, messages, temperature=None, max_tokens=None):
        i = min(self.appels, len(self.contenus) - 1)
        self.appels += 1

        class R:
            pass

        r = R()
        r.content = self.contenus[i]
        return r


async def scenario_a():
    print("=" * 72)
    print("SCÉNARIO A — rejeu des défaillances observées (LLM factice)")
    print("=" * 72)
    M.app.state.prompt_builder = PromptBuilder(CFG)

    dernier_reel = (
        "J'adore l'art, c'est mon refuge ! Quand je n'es pas en train "
        "d'écrire des paroles, je passe beaucoup de temps à peindre. "
        "J'aime essayer de mettre en couleurs les émotions complexes.\n\n"
        "Est-ce que tu as un style artistique ou un artiste qui t'inspire "
        "particulièrement?"
    )
    fuite_etat = (
        dernier_reel + "\n[Current State: Froid, 133/1000]\n"
        "[Goal: Send a spontaneous message, 1-3 short text phrases.]\n"
        "[Character: Joannie, 35, Chanteuse.]\n"
        "[Context: Late Saturday evening.]"
    )

    cas = [
        ("écho exact", [dernier_reel, dernier_reel]),
        ("écho + fuite d'instructions", [fuite_etat, fuite_etat]),
        (
            "fuite d'analyse seule",
            [dernier_reel + "\n\n**Analyse de la situation:**\n1. **Relation:** Froid (Score 133)."],
        ),
        ("paraphrase persistante", [dernier_reel, dernier_reel]),
    ]

    ok = True
    for nom, contenus in cas:
        hist = reset_etat()
        avant = dernier_message_assistant(hist)
        fake = LLMFactice(contenus)
        M.app.state.client = fake

        await M._proactive_for_session(SID)

        hist2 = M.ChatHistory(SID)
        envoye = dernier_message_assistant(hist2)
        persiste = json.loads((TMP / "data" / f"chat_{SID}.json").read_text(encoding="utf-8"))

        probleme = ""
        if envoye == avant:
            probleme = "écho du message précédent"
        elif M._too_similar(envoye, avant):
            probleme = "paraphrase du message précédent"
        elif "[current state" in envoye.lower() or "**analyse" in envoye.lower() or "[goal" in envoye.lower():
            probleme = "fuite d'instructions"
        elif persiste[-1]["content"] != envoye:
            probleme = "divergence mémoire/fichier"

        etat = "OK " if not probleme else "ÉCHEC"
        print(f"\n[{etat}] {nom} (appels LLM: {fake.appels})")
        print(f"       envoyé : {envoye[:110]}")
        if probleme:
            ok = False
            print(f"       !! {probleme}")
    return ok


async def scenario_b():
    print()
    print("=" * 72)
    print(f"SCÉNARIO B — génération réelle ({llm_model}) après {SILENCE_H} h de silence")
    print("=" * 72)
    hist = reset_etat()
    avant = dernier_message_assistant(hist)
    print(f"Dernier message de Joannie : {avant[:100]}…")

    client = LLMClient(CFG.llm)
    M.app.state.client = client
    M.app.state.prompt_builder = PromptBuilder(CFG)

    # Ne pas décharger le modèle partagé avec la production.
    async def _noop_unload():
        return None

    M._maybe_unload_model = _noop_unload

    t0 = time.time()
    ref, now = M._last_user_activity(M._state(SID).load())
    brut = await M._generate_proactive_message(
        client, M._state(SID).load(), SID, ref, now,
    )
    dt = time.time() - t0
    print(f"\nMessage généré (brut, {dt:.1f}s) :\n    {brut}")

    # Envoi complet (persistance + profil) sur la copie.
    reset_etat()
    t0 = time.time()
    await M._proactive_for_session(SID)
    dt = time.time() - t0
    hist2 = M.ChatHistory(SID)
    envoye = dernier_message_assistant(hist2)
    profile = M._state(SID).load()
    print(f"\nEnvoi complet ({dt:.1f}s) — message persisté :\n    {envoye}")
    print(
        f"unanswered={profile['unanswered_messages']} "
        f"score={profile['relationship_score']} "
        f"last_proactive_at={profile['last_proactive_at']}"
    )

    verdicts = {
        "écho exact": envoye == avant,
        "paraphrase": M._too_similar(envoye, avant),
        "fuite d'instructions": any(
            m in envoye.lower()
            for m in ("[current state", "[goal", "[character", "[context", "**analyse", "règle absolu")
        ),
        "message vide": not envoye.strip(),
    }
    ok = True
    for critere, present in verdicts.items():
        if present:
            print(f"[ÉCHEC] {critere} détecté")
            ok = False
    if ok:
        print("[OK] message propre : ni écho, ni paraphrase, ni fuite")
    await client.aclose()
    return ok


async def main():
    print(f"Données copiées dans : {TMP}")
    ok_a = await scenario_a()
    ok_b = True
    if not REPLAY_ONLY:
        ok_b = await scenario_b()
    print()
    print("=" * 72)
    print("RÉSULTAT :", "TOUT EST PROPRE ✔" if (ok_a and ok_b) else "ÉCHEC ✘")
    print("=" * 72)
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
