// Album photo — toutes les photos de la session (portrait + photos prises).
// Clic sur une photo : visionneuse plein écran (navigation clavier ←/→, Échap).

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiPhotos, apiRegenererPhoto, apiSession } from "../api/rest";
import { useAmie } from "../store";

export function AlbumPage() {
  const { sid } = useParams<{ sid: string }>();
  const queryClient = useQueryClient();
  // Nom du personnage : source de vérité = l'API de la session (le store
  // peut contenir une AUTRE rencontre si on arrive par navigation directe,
  // ou rien du tout après un chargement froid de la page).
  const nomStore = useAmie((s) => s.profile?.character.name ?? "");
  const { data: session } = useQuery({
    queryKey: ["session", sid],
    queryFn: () => apiSession(sid!),
    enabled: !!sid,
    retry: 1,
  });
  const characterName = session?.character?.name || nomStore;
  const [selected, setSelected] = useState<number | null>(null);
  // Fichier en cours de régénération (indicateur + boutons désactivés).
  const [regenEnCours, setRegenEnCours] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["photos", sid],
    queryFn: () => apiPhotos(sid!),
    enabled: !!sid,
  });

  const photos = data?.photos ?? [];

  const regen = useMutation({
    mutationFn: (file: string) => apiRegenererPhoto(sid!, file),
    onSuccess: (r) => {
      setRegenEnCours(null);
      setMessage(
        r.photo?.seed !== undefined
          ? `✨ Photo régénérée (seed ${r.photo.seed}).`
          : "✨ Photo régénérée.",
      );
      queryClient.invalidateQueries({ queryKey: ["photos", sid] });
    },
    onError: (e) => {
      setRegenEnCours(null);
      setMessage(e instanceof Error ? e.message : "Régénération impossible.");
    },
  });

  function demanderRegeneration(file: string | undefined) {
    if (!file || regenEnCours) return;
    if (
      window.confirm(
        "Régénérer cette photo avec une nouvelle seed ? L'image actuelle sera remplacée dans l'album (la génération peut prendre jusqu'à 60 s).",
      )
    ) {
      setMessage("");
      setRegenEnCours(file);
      regen.mutate(file);
    }
  }

  // Ferme la visionneuse quand on change de session.
  useEffect(() => setSelected(null), [sid]);

  // Clavier : Échap ferme, flèches naviguent. Verrouille le scroll du fond.
  useEffect(() => {
    if (selected === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
      else if (e.key === "ArrowRight")
        setSelected((i) => (i === null ? null : (i + 1) % photos.length));
      else if (e.key === "ArrowLeft")
        setSelected((i) =>
          i === null ? null : (i - 1 + photos.length) % photos.length,
        );
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [selected === null, photos.length]);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-xl font-semibold text-rose-100">
          🖼 Album{characterName ? ` — ${characterName}` : ""}
        </h2>
        <Link
          to={`/session/${sid}`}
          className="rounded-md border border-rose-800/60 px-3 py-1.5 text-sm text-rose-200 transition hover:bg-rose-900/40"
        >
          ← Retour à la conversation
        </Link>
      </div>

      {isLoading ? (
        <p className="text-sm text-rose-200/50">Chargement…</p>
      ) : photos.length === 0 ? (
        <div className="mt-16 text-center">
          <div className="mb-3 text-5xl">📷</div>
          <p className="text-rose-200/60">
            Aucune photo pour l'instant.
            <br />
            Demandez-en depuis la conversation !
          </p>
        </div>
      ) : (
        <>
          {message && (
            <p className="mb-4 rounded-lg border border-rose-900/50 bg-[#24101c]/80 px-4 py-2 text-center text-sm text-rose-100/80">
              {message}
            </p>
          )}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {photos.map((p, i) => (
              <figure
                key={p.url}
                className="relative overflow-hidden rounded-xl border border-rose-900/40 bg-[#1a0b14]"
              >
                <button
                  type="button"
                  onClick={() => setSelected(i)}
                  aria-label={
                    p.caption
                      ? `Agrandir : ${p.caption}`
                      : "Agrandir la photo"
                  }
                  className="group block w-full cursor-zoom-in"
                >
                  <img
                    src={p.url}
                    alt={p.caption || "photo"}
                    className={
                      "aspect-square w-full object-cover transition duration-200 group-hover:scale-[1.03] group-hover:brightness-110" +
                      (regenEnCours === p.file ? " opacity-40" : "")
                    }
                  />
                </button>
                {/* Régénération (autre seed) — photos issues d'une génération */}
                {p.regenerable && p.file && (
                  <button
                    type="button"
                    onClick={() => demanderRegeneration(p.file)}
                    disabled={!!regenEnCours}
                    title="Régénérer cette image avec une autre seed (remplace la photo actuelle)"
                    aria-label={`Régénérer : ${p.caption || "photo"}`}
                    className="absolute right-2 top-2 flex h-9 w-9 items-center justify-center rounded-full bg-black/60 text-lg text-white/90 transition hover:bg-rose-600/80 disabled:cursor-wait disabled:opacity-60"
                  >
                    {regenEnCours === p.file ? "⏳" : "🔄"}
                  </button>
                )}
                <figcaption className="px-2 py-1.5 text-center text-xs text-rose-200/50">
                  {p.caption || (p.kind === "portrait" ? "Photo de profil" : "Souvenir")}
                </figcaption>
              </figure>
            ))}
          </div>
        </>
      )}

      {/* Visionneuse plein écran */}
      {selected !== null && photos[selected] && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Visionneuse photo"
          className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/92 p-4 backdrop-blur-sm"
          onClick={() => setSelected(null)}
        >
          <img
            src={photos[selected].url}
            alt={photos[selected].caption || "photo"}
            className="max-h-[82vh] max-w-full rounded-lg object-contain shadow-2xl shadow-black"
            onClick={(e) => e.stopPropagation()}
          />
          <p className="mt-3 max-w-xl text-center text-sm text-rose-100/80">
            {photos[selected].caption ||
              (photos[selected].kind === "portrait"
                ? "Photo de profil"
                : "Souvenir")}
            <span className="ml-2 text-rose-200/40">
              {selected + 1}/{photos.length}
            </span>
          </p>

          <button
            type="button"
            onClick={() => setSelected(null)}
            aria-label="Fermer"
            className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-xl text-white transition hover:bg-white/20"
          >
            ✕
          </button>

          {/* Régénération : même scène, nouvelle seed (image ratée ?). */}
          {photos[selected].regenerable && photos[selected].file && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                demanderRegeneration(photos[selected].file);
              }}
              disabled={!!regenEnCours}
              className="absolute left-4 top-4 flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-sm text-white transition hover:bg-rose-600/80 disabled:cursor-wait disabled:opacity-60"
            >
              {regenEnCours === photos[selected].file
                ? "⏳ Régénération…"
                : "🔄 Régénérer (autre seed)"}
            </button>
          )}

          {photos.length > 1 && (
            <>
              <button
                type="button"
                aria-label="Photo précédente"
                onClick={(e) => {
                  e.stopPropagation();
                  setSelected(
                    (i) => (i! - 1 + photos.length) % photos.length,
                  );
                }}
                className="absolute left-3 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-2xl text-white transition hover:bg-white/20"
              >
                ‹
              </button>
              <button
                type="button"
                aria-label="Photo suivante"
                onClick={(e) => {
                  e.stopPropagation();
                  setSelected((i) => (i! + 1) % photos.length);
                }}
                className="absolute right-3 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-2xl text-white transition hover:bg-white/20"
              >
                ›
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
