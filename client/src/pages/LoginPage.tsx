// Page de connexion — nom + mot de passe. Crée le compte à la première
// connexion (le serveur renvoie `nouveau: true`).
// Avertissement 18+ : case de déclaration obligatoire avant connexion
// (mémorisée localement pour les visites suivantes).

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiLogin } from "../api/rest";
import { useAmie } from "../store";

const CLE_MAJEUR = "amie_majeur_ok";

export function LoginPage() {
  const [nom, setNom] = useState(useAmie.getState().user);
  const [mdp, setMdp] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [majeur, setMajeur] = useState(
    () => localStorage.getItem(CLE_MAJEUR) === "1",
  );
  const setUser = useAmie((s) => s.setUser);
  const setPassword = useAmie((s) => s.setPassword);
  const navigate = useNavigate();

  function cocherMajeur(v: boolean) {
    setMajeur(v);
    if (v) localStorage.setItem(CLE_MAJEUR, "1");
    else localStorage.removeItem(CLE_MAJEUR);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!majeur) return;
    setErreur(null);
    setLoading(true);
    try {
      const res = await apiLogin(nom.trim(), mdp);
      setUser(res.user);
      setPassword(mdp);
      navigate("/sessions");
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl border border-rose-900/40 bg-[#24101c]/80 p-8 shadow-xl shadow-rose-950/30"
      >
        <div className="mb-6 text-center">
          <div className="mb-2 text-4xl">💕</div>
          <h2 className="text-2xl font-semibold text-rose-100">Bienvenue</h2>
          <p className="mt-1 text-sm text-rose-200/60">
            Connectez-vous pour retrouver vos rencontres
          </p>
        </div>

        <label className="mb-1 block text-sm font-medium text-rose-200/80">
          Votre prénom
        </label>
        <input
          value={nom}
          onChange={(e) => setNom(e.target.value)}
          placeholder="ex : Alex"
          autoFocus
          required
          className="mb-4 w-full rounded-lg border border-rose-900/50 bg-[#1a0b14] px-3 py-2 text-rose-50 outline-none transition focus:border-rose-500"
        />

        <label className="mb-1 block text-sm font-medium text-rose-200/80">
          Mot de passe
        </label>
        <input
          type="password"
          value={mdp}
          onChange={(e) => setMdp(e.target.value)}
          placeholder="4 caractères minimum"
          required
          minLength={4}
          className="w-full rounded-lg border border-rose-900/50 bg-[#1a0b14] px-3 py-2 text-rose-50 outline-none transition focus:border-rose-500"
        />

        {/* Avertissement contenu adultes */}
        <div className="mt-4 rounded-lg border border-amber-700/50 bg-amber-950/30 p-3">
          <p className="text-xs font-semibold text-amber-300">
            🔒 Contenu pour adulte averti (18 ans +)
          </p>
          <p className="mt-1 text-[11px] leading-snug text-amber-200/70">
            Cette application simule des relations virtuelles et peut générer
            des contenus sensibles à mesure que la relation évolue.
          </p>
          <label className="mt-2 flex cursor-pointer items-start gap-2 text-xs text-amber-100/90">
            <input
              type="checkbox"
              checked={majeur}
              onChange={(e) => cocherMajeur(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 accent-amber-500"
            />
            <span>Je certifie avoir 18 ans ou plus.</span>
          </label>
        </div>

        {erreur && (
          <p className="mt-3 rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            {erreur}
          </p>
        )}

        <button
          type="submit"
          disabled={loading || !majeur || !nom.trim() || mdp.length < 4}
          className="mt-6 w-full rounded-lg bg-gradient-to-r from-rose-500 to-fuchsia-500 py-2.5 font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? "Connexion…" : "Se connecter"}
        </button>
        <p className="mt-3 text-center text-xs text-rose-200/40">
          Première visite ? Votre compte sera créé automatiquement.
        </p>
      </form>
    </div>
  );
}
