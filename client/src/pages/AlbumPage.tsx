// Album photo — toutes les photos de la session (portrait + photos prises).

import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiPhotos } from "../api/rest";
import { useAmie } from "../store";

export function AlbumPage() {
  const { sid } = useParams<{ sid: string }>();
  const user = useAmie((s) => s.user);
  const characterName = useAmie((s) => s.profile?.character.name ?? "");

  const { data, isLoading } = useQuery({
    queryKey: ["photos", sid, user],
    queryFn: () => apiPhotos(sid!, user),
    enabled: !!sid,
  });

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
      ) : (data?.photos ?? []).length === 0 ? (
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
          {data!.photos.map((p) => (
            <figure
              key={p.url}
              className="overflow-hidden rounded-xl border border-rose-900/40 bg-[#1a0b14]"
            >
              <img src={p.url} alt={p.caption || "photo"} className="aspect-square w-full object-cover" />
              <figcaption className="px-2 py-1.5 text-center text-xs text-rose-200/50">
                {p.caption || (p.kind === "portrait" ? "Photo de profil" : "Souvenir")}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}
