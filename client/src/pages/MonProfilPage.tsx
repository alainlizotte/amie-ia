// Page « Mon profil » — la fiche « dating app » de l'utilisateur, selon les
// mêmes catégories que les personnages IA. Le personnage reçoit cette fiche
// dans son prompt : il sait avec qui il parle. Photo de profil optionnelle,
// analysée par le modèle vision (description auto injectée au personnage).

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiMonProfil,
  apiPhotoProfilBlob,
  apiSauverMonProfil,
  apiSupprimerCompte,
  apiUploadPhotoProfil,
  setToken,
} from "../api/rest";
import type { MonProfil } from "../api/types";
import { useAmie } from "../store";

type Champs = MonProfil["profil"];

const VIDE: Champs = {
  name: "",
  age: "",
  gender: "",
  title: "",
  occupation: "",
  interests: "",
  appearance: "",
  personality: "",
  histoire: "",
  parcours_amoureux: "",
  preferences: "",
};

function champ(
  label: string,
  key: keyof Champs,
  form: Champs,
  setForm: (c: Champs) => void,
  textarea = false,
  placeholder = "",
) {
  const cls =
    "w-full rounded-lg border border-rose-900/50 bg-[#1a0b14] px-3 py-2 text-sm text-rose-50 outline-none transition focus:border-rose-500";
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-rose-200/80">
        {label}
      </label>
      {textarea ? (
        <textarea
          value={form[key]}
          onChange={(e) => setForm({ ...form, [key]: e.target.value })}
          placeholder={placeholder}
          rows={3}
          maxLength={1200}
          className={cls}
        />
      ) : (
        <input
          value={form[key]}
          onChange={(e) => setForm({ ...form, [key]: e.target.value })}
          placeholder={placeholder}
          maxLength={300}
          className={cls}
        />
      )}
    </div>
  );
}

export function MonProfilPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const setUser = useAmie((s) => s.setUser);
  const reset = useAmie((s) => s.reset);
  const [form, setForm] = useState<Champs>(VIDE);
  const [erreur, setErreur] = useState("");
  const [analyseEnCours, setAnalyseEnCours] = useState(false);
  const [confirmerSuppression, setConfirmerSuppression] = useState(false);
  const fichierRef = useRef<HTMLInputElement>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["mon-profil"],
    queryFn: apiMonProfil,
    // Pendant l'analyse vision : interroge jusqu'à description ou erreur.
    refetchInterval: analyseEnCours ? 3000 : false,
  });

  useEffect(() => {
    if (data) {
      setForm({ ...VIDE, ...data.profil });
      if (analyseEnCours && (data.photo_description || data.photo_erreur)) {
        setAnalyseEnCours(false);
      }
    }
  }, [data, analyseEnCours]);

  const photo = useQuery({
    queryKey: ["photo-profil", data?.photo_url],
    queryFn: apiPhotoProfilBlob,
    enabled: !!data?.photo_url,
  });

  const sauver = useMutation({
    mutationFn: () => apiSauverMonProfil(form),
    onSuccess: () => {
      // Profil enregistré → retour automatique à la page principale.
      queryClient.invalidateQueries({ queryKey: ["mon-profil"] });
      navigate("/sessions");
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : "Erreur inconnue"),
  });

  const upload = useMutation({
    mutationFn: (dataUrl: string) => apiUploadPhotoProfil(dataUrl),
    onSuccess: (r) => {
      setErreur("");
      setAnalyseEnCours(r.analyse_en_cours);
      queryClient.invalidateQueries({ queryKey: ["mon-profil"] });
      queryClient.invalidateQueries({ queryKey: ["photo-profil"] });
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : "Erreur inconnue"),
  });

  // Suppression définitive du compte : purge serveur de toutes les données,
  // puis déconnexion locale complète (store, token, cache React Query).
  const supprimerCompte = useMutation({
    mutationFn: () => apiSupprimerCompte(),
    onSuccess: () => {
      setConfirmerSuppression(false);
      setUser("");
      setToken("");
      reset();
      queryClient.clear();
      navigate("/login");
    },
    onError: (e) => {
      setConfirmerSuppression(false);
      setErreur(e instanceof Error ? e.message : "Erreur inconnue");
    },
  });

  function choisirFichier(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) {
      setErreur("Image trop volumineuse (max ~8 Mo).");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => upload.mutate(String(reader.result));
    reader.readAsDataURL(f);
    e.target.value = "";
  }

  if (isLoading) {
    return <p className="p-6 text-sm text-rose-200/50">Chargement…</p>;
  }

  const enAttente = analyseEnCours && !data?.photo_description && !data?.photo_erreur;

  return (
    <div className="mx-auto max-w-2xl p-6">
      <button
        onClick={() => navigate("/sessions")}
        className="mb-4 inline-flex items-center gap-1.5 rounded-md border border-rose-800/60 px-3 py-1.5 text-sm text-rose-200 transition hover:bg-rose-900/40"
      >
        ← Retour à mes rencontres
      </button>
      <h2 className="mb-1 text-xl font-semibold text-rose-100">Mon profil</h2>
      <p className="mb-6 text-sm text-rose-200/60">
        Comme sur une vraie application : ton match connaît ce que tu écris ici.
        Les personnages IA s'y réfèrent naturellement pendant vos discussions.
      </p>

      {/* Photo de profil + analyse vision */}
      <div className="mb-6 flex gap-4 rounded-2xl border border-rose-900/40 bg-[#24101c]/80 p-5">
        <div className="shrink-0">
          {photo.data ? (
            <img
              src={photo.data}
              alt="Ma photo"
              className="h-28 w-28 rounded-xl object-cover"
            />
          ) : (
            <div className="flex h-28 w-28 items-center justify-center rounded-xl border border-dashed border-rose-900/60 text-3xl">
              📷
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => fichierRef.current?.click()}
              disabled={upload.isPending}
              className="rounded-lg border border-rose-800/60 px-3 py-1.5 text-sm text-rose-200 transition hover:bg-rose-900/40 disabled:opacity-40"
            >
              {upload.isPending ? "…" : data?.photo_url ? "Changer la photo" : "Ajouter une photo"}
            </button>
            <input
              ref={fichierRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={choisirFichier}
              className="hidden"
            />
          </div>
          {enAttente && (
            <p className="mt-2 text-xs text-amber-300/90">
              🧠 Analyse de la photo par le modèle vision… (quelques secondes,
              plus si le modèle doit se recharger)
            </p>
          )}
          {data?.photo_description && !enAttente && (
            <p className="mt-2 text-xs text-emerald-300/80">
              ✓ Photo ajoutée à ton profil — tes matchs peuvent te voir.
            </p>
          )}
          {data?.photo_erreur && !enAttente && (
            <p className="mt-2 text-xs text-amber-300/80">{data.photo_erreur}</p>
          )}
        </div>
      </div>

      {/* Fiche — mêmes catégories que les personnages */}
      <div className="space-y-4 rounded-2xl border border-rose-900/40 bg-[#24101c]/80 p-5">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {champ("Prénom", "name", form, setForm, false, "ex : Alex")}
          {champ("Âge", "age", form, setForm, false, "ex : 32")}
          <div>
            <label className="mb-1 block text-sm font-medium text-rose-200/80">Genre</label>
            <select
              value={form.gender}
              onChange={(e) => setForm({ ...form, gender: e.target.value })}
              className="w-full rounded-lg border border-rose-900/50 bg-[#1a0b14] px-3 py-2 text-sm text-rose-50 outline-none focus:border-rose-500"
            >
              <option value="">—</option>
              <option value="F">Femme</option>
              <option value="H">Homme</option>
            </select>
          </div>
          {champ("Surnom", "title", form, setForm, false, "ex : Al, le calme incarné")}
        </div>
        {champ("Apparence (si pas de photo)", "appearance", form, setForm, true, "Décris-toi librement…")}
        {champ("Personnalité", "personality", form, setForm, true, "ex : curieux, calme, blague facile…")}
        {champ("Métier / études", "occupation", form, setForm, false, "ex : technicien en informatique")}
        {champ("Centres d'intérêt", "interests", form, setForm, false, "ex : cuisine, vélo, séries…")}
        {champ("Ton histoire", "histoire", form, setForm, true, "D'où tu viens, ce qui t'a façonné…")}
        {champ("Situation amoureuse", "parcours_amoureux", form, setForm, true, "ex : célibataire depuis un an…")}
        {champ("Ce que tu recherches", "preferences", form, setForm, true, "ex : discussions sincères, rire…")}
      </div>

      {erreur && (
        <p className="mt-3 rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {erreur}
        </p>
      )}

      <button
        onClick={() => sauver.mutate()}
        disabled={sauver.isPending}
        className="mt-5 w-full rounded-lg bg-gradient-to-r from-rose-500 to-fuchsia-500 py-2.5 font-semibold text-white transition hover:brightness-110 disabled:opacity-40"
      >
        {sauver.isPending ? "…" : "Enregistrer mon profil"}
      </button>

      {/* Zone de danger — suppression définitive du compte */}
      <div className="mt-8 rounded-2xl border border-red-900/50 bg-[#1a0b14]/80 p-5">
        <h3 className="text-sm font-semibold text-red-300">Zone de danger</h3>
        <p className="mt-1 text-sm text-red-200/70">
          Supprimer mon compte efface définitivement ma fiche, ma photo, toutes
          mes rencontres avec leurs messages et leurs albums. Aucun retour
          possible.
        </p>
        <button
          onClick={() => setConfirmerSuppression(true)}
          className="mt-3 rounded-lg border border-red-800/70 px-3 py-1.5 text-sm text-red-300 transition hover:bg-red-950/60"
        >
          🗑️ Supprimer mon compte et mes données
        </button>
      </div>

      {/* Confirmation de suppression (modale) */}
      {confirmerSuppression && (
        <div
          className="fixed inset-0 z-50 flex"
          role="dialog"
          aria-modal="true"
          aria-label="Confirmer la suppression du compte"
        >
          <button
            type="button"
            aria-label="Fermer"
            onClick={() => setConfirmerSuppression(false)}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <div className="relative z-10 m-auto w-[88%] max-w-sm rounded-2xl border border-red-900/50 bg-[#1a0b14]/95 p-5 shadow-2xl">
            <h3 className="text-lg font-semibold text-red-200">
              Supprimer mon compte ?
            </h3>
            <p className="mt-2 text-sm text-rose-200/70">
              Ta fiche, ta photo, toutes tes rencontres, leurs messages et
              albums photos seront définitivement effacés. Cette action est
              irréversible.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmerSuppression(false)}
                className="rounded-lg border border-rose-800/60 px-3 py-1.5 text-sm text-rose-200 transition hover:bg-rose-900/40"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => supprimerCompte.mutate()}
                disabled={supprimerCompte.isPending}
                className="rounded-lg bg-red-700 px-3 py-1.5 text-sm font-semibold text-white transition hover:bg-red-600 disabled:opacity-40"
              >
                {supprimerCompte.isPending ? "Suppression…" : "Tout supprimer"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
