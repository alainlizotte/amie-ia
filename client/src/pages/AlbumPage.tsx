// Album photo — toutes les photos de la session (portrait + photos prises).
// Clic sur une photo : visionneuse plein écran (navigation clavier ←/→, Échap).

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiPhotos } from "../api/rest";
import { useAmie } from "../store";

export function AlbumPage() {
  const { sid } = useParams<{ sid: string }>();
  const user = useAmie((s) => s.user);
  const characterName = useAmie((s) => s.profile?.character.name ?? "");
  const [selected, setSelected] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["photos", sid, user],
    queryFn: () => apiPhotos(sid!, user),
    enabled: !!sid,
  });

  const photos = data?.photos ?? [];

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
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {photos.map((p, i) => (
            <figure
              key={p.url}
              className="overflow-hidden rounded-xl border border-rose-900/40 bg-[#1a0b14]"
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
                  className="aspect-square w-full object-cover transition duration-200 group-hover:scale-[1.03] group-hover:brightness-110"
                />
              </button>
              <figcaption className="px-2 py-1.5 text-center text-xs text-rose-200/50">
                {p.caption || (p.kind === "portrait" ? "Photo de profil" : "Souvenir")}
              </figcaption>
            </figure>
          ))}
        </div>
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
