// Page de session — chat + panneau latéral (photo permanente, barre de
// relation, album). Le WS se connecte via useChatSocket.
// Mobile : le panneau latéral est masqué — le bouton ⓘ de l'en-tête
// l'affiche dans une vue superposée.

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAmie } from "../store";
import { useChatSocket } from "../hooks/useChatSocket";
import { ChatPanel } from "../components/ChatPanel";
import { CharacterPhoto } from "../components/CharacterPhoto";
import { RelationshipBar } from "../components/RelationshipBar";

/** Stades autorisant les photos (miroir REFUSALS_BY_STAGE serveur). */
const PHOTO_STAGES = new Set(["neutre", "chaleureux", "proche"]);

export function SessionPage() {
  const { sid } = useParams<{ sid: string }>();
  const socketRef = useChatSocket(sid);
  // Vue du panneau latéral superposée (mobile uniquement).
  const [showInfo, setShowInfo] = useState(false);

  const user = useAmie((s) => s.user);
  const profile = useAmie((s) => s.profile);
  const messages = useAmie((s) => s.messages);
  const typing = useAmie((s) => s.typing);
  const busy = useAmie((s) => s.busy);
  const status = useAmie((s) => s.status);
  const joined = useAmie((s) => s.joined);
  const authError = useAmie((s) => s.authError);

  if (authError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-2xl">🔒</p>
        <p className="text-rose-200/70">{authError}</p>
        <Link to="/sessions" className="text-sm text-fuchsia-300 underline">
          Retour à mes rencontres
        </Link>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-rose-200/50">
        Connexion à la rencontre…
      </div>
    );
  }

  const canPhoto = PHOTO_STAGES.has(profile.stage);

  // Contenu du panneau latéral — partagé entre la colonne de droite
  // (desktop) et la vue superposée ouverte par le bouton ⓘ (mobile).
  const sideContent = (
    <>
      <CharacterPhoto
        url={profile.portrait_url}
        name={profile.character.name}
        gender={profile.character.gender}
        pending={!profile.portrait_url && profile.interaction_count === 0}
      />

      <div className="rounded-2xl border border-rose-900/40 bg-[#24101c]/80 p-4">
        <RelationshipBar score={profile.score} stage={profile.stage} />
        <dl className="mt-3 space-y-1 text-xs text-rose-200/50">
          <div className="flex justify-between">
            <dt>Messages échangés</dt>
            <dd>{profile.interaction_count}</dd>
          </div>
          {profile.events_total > 0 && (
            <div className="flex justify-between">
              <dt>Moments vécus</dt>
              <dd>
                {profile.events_consumed}/{profile.events_total}
              </dd>
            </div>
          )}
        </dl>
      </div>

      {(profile.character.interests || profile.character.occupation) && (
        <div className="rounded-2xl border border-rose-900/40 bg-[#24101c]/80 p-4 text-xs leading-relaxed text-rose-200/60">
          {profile.character.occupation && (
            <p className="mb-1">💼 {profile.character.occupation}</p>
          )}
          {profile.character.interests && <p>🎯 {profile.character.interests}</p>}
        </div>
      )}

      {!joined && (
        <p className="text-center text-xs italic text-rose-200/30">
          Reconnexion au serveur…
        </p>
      )}
      <p className="text-center text-[10px] text-rose-200/20">session : {user}</p>
    </>
  );

  return (
    <div className="mx-auto flex h-full max-w-5xl gap-4 p-4">
      {/* Colonne chat */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-rose-900/40 bg-[#24101c]/60">
        <div className="flex items-center justify-between border-b border-rose-900/40 px-4 py-2.5">
          <div className="flex items-center gap-3">
            <Link
              to="/sessions"
              title="Retour à Mes rencontres"
              className="rounded-md border border-rose-800/60 px-2.5 py-1 text-xs text-rose-200 transition hover:bg-rose-900/40"
            >
              ←
            </Link>
            <div>
              <h2 className="font-semibold text-rose-100">{profile.character.name}</h2>
              <p className="text-xs text-rose-200/40">{profile.character.title}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Mobile : ouvre la vue du panneau latéral (i encerclé). */}
            <button
              type="button"
              onClick={() => setShowInfo(true)}
              title="Informations"
              aria-label="Afficher les informations"
              className="rounded-md border border-rose-800/60 px-2.5 py-1 text-sm leading-none text-rose-200 transition hover:bg-rose-900/40 md:hidden"
            >
              ⓘ
            </button>
            <Link
              to={`/session/${sid}/album`}
              className="rounded-md border border-rose-800/60 px-3 py-1 text-xs text-rose-200 transition hover:bg-rose-900/40"
            >
              🖼 Album ({profile.photos_count})
            </Link>
          </div>
        </div>
        <ChatPanel
          messages={messages}
          typing={typing}
          busy={busy}
          status={status}
          characterName={profile.character.name}
          canRequestPhoto={canPhoto}
          onSend={(text) => {
            useAmie.getState().setBusy(true);
            socketRef.current?.say(text);
          }}
          onPhotoRequest={(hint) => {
            // Feedback instantané au clic (le serveur confondra ensuite
            // avec son propre événement image_pending).
            useAmie.getState().setStatus(
              "📸 Photo en cours de génération (jusqu'à 60 s)...",
            );
            socketRef.current?.photoRequest(hint);
          }}
        />
      </div>

      {/* Panneau latéral (desktop ; sur mobile, voir le bouton ⓘ) */}
      <aside className="hidden w-72 shrink-0 flex-col gap-4 overflow-y-auto md:flex">
        {sideContent}
      </aside>

      {/* Mobile : vue superposée du panneau latéral (bouton ⓘ de l'en-tête). */}
      {showInfo && (
        <div
          className="fixed inset-0 z-50 flex md:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Informations sur la rencontre"
        >
          <button
            type="button"
            aria-label="Fermer"
            onClick={() => setShowInfo(false)}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <div className="pb-safe-area relative z-10 m-auto flex max-h-[85dvh] w-[88%] max-w-sm flex-col gap-4 overflow-y-auto rounded-2xl border border-rose-900/40 bg-[#1a0b14]/95 p-4 shadow-2xl">
            <button
              type="button"
              onClick={() => setShowInfo(false)}
              aria-label="Fermer"
              className="absolute right-3 top-3 z-20 rounded-md border border-rose-800/60 bg-[#24101c]/90 px-2 py-0.5 text-xs text-rose-200 transition hover:bg-rose-900/40"
            >
              ✕
            </button>
            {sideContent}
          </div>
        </div>
      )}
    </div>
  );
}
