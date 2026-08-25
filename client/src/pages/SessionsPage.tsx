// Page « Mes rencontres » — liste des sessions de l'utilisateur + création.
// Badge rouge « !n » sur l'encadré d'un personnage : nombre de messages
// spontanés envoyés sans réponse (disparaît dès que vous lui répondez).

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDeleteSession, apiSessions } from "../api/rest";
import { STAGE_LABELS } from "../api/types";
import { CharacterPicker } from "../components/CharacterPicker";
import { useAmie } from "../store";

export function SessionsPage() {
  const setSessionId = useAmie((s) => s.setSessionId);
  const reset = useAmie((s) => s.reset);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["sessions"],
    queryFn: apiSessions,
    refetchInterval: 5000, // rafraîchit pendant la génération des portraits
  });

  const del = useMutation({
    mutationFn: (sid: string) => apiDeleteSession(sid),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });

  function openSession(sid: string) {
    reset();
    setSessionId(sid);
    navigate(`/session/${sid}`);
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-xl font-semibold text-rose-100">Mes rencontres</h2>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="rounded-lg bg-gradient-to-r from-rose-500 to-fuchsia-500 px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110"
        >
          {showCreate ? "Annuler" : "+ Nouvelle rencontre"}
        </button>
      </div>

      {showCreate && (
        <div className="mb-6 rounded-2xl border border-rose-900/40 bg-[#24101c]/80 p-5">
          <CharacterPicker
            onCreated={(sid) => {
              setShowCreate(false);
              openSession(sid);
            }}
          />
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-rose-200/50">Chargement…</p>
      ) : (data?.sessions ?? []).length === 0 ? (
        <div className="mt-16 text-center">
          <div className="mb-3 text-5xl">🌹</div>
          <p className="text-rose-200/60">
            Aucune rencontre pour l'instant.
            <br />
            Lancez-vous avec « Nouvelle rencontre » !
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {data!.sessions.map((s) => (
            <li
              key={s.session_id}
              className="relative flex items-center gap-4 rounded-xl border border-rose-900/40 bg-[#24101c]/80 p-4 transition hover:border-rose-500/50"
            >
              {/* Badge messages sans réponse : compteur dans un cercle rouge */}
              {s.unanswered_messages > 0 && (
                <span
                  title={`${s.unanswered_messages} message(s) de ${s.character.name} sans réponse`}
                  className="absolute -right-2 -top-2 z-10 flex h-8 min-w-8 items-center justify-center rounded-full border-2 border-[#24101c] bg-red-600 px-1.5 text-sm font-bold text-white shadow-lg shadow-red-950/50"
                >
                  {s.unanswered_messages}
                </span>
              )}
              <button onClick={() => openSession(s.session_id)} className="flex min-w-0 flex-1 items-center gap-4 text-left">
                {s.portrait_url ? (
                  <img
                    src={s.portrait_url}
                    alt={s.character.name}
                    className="h-14 w-14 shrink-0 rounded-full object-cover ring-2 ring-rose-500/40"
                  />
                ) : (
                  <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-[#331627] text-xl ring-2 ring-rose-900/50">
                    {s.character.gender === "M" ? "👨" : "👩"}
                  </div>
                )}
                <div className="min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate font-semibold text-rose-100">{s.character.name}</span>
                    <span className="shrink-0 rounded-full bg-fuchsia-500/15 px-2 py-0.5 text-xs text-fuchsia-300">
                      {STAGE_LABELS[s.stage] ?? s.stage}
                    </span>
                  </div>
                  <p className="truncate text-sm text-rose-200/50">
                    {s.last_message || `${s.interaction_count} message(s)`}
                  </p>
                </div>
              </button>
              <button
                onClick={() => {
                  if (confirm(`Supprimer la rencontre avec ${s.character.name} ?`)) {
                    del.mutate(s.session_id);
                  }
                }}
                title="Supprimer"
                className="shrink-0 rounded-md px-2 py-1 text-rose-300/40 transition hover:bg-red-950/40 hover:text-red-300"
              >
                🗑
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
