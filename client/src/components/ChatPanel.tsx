// Panneau de chat — fil de messages, saisie, boutons « demander une photo »
// et « lancer un mini-jeu », réponses rapides du jeu en cours.

import { useEffect, useRef, useState } from "react";
import { renderMarkdown } from "../utils/markdown";
import type { ChatMessage, GameInfo, ProfilVoix } from "../api/types";
import { arreterVoix, parler, voixDisponible } from "../utils/voix";

/** Mini-jeux proposés (ids miroir server/relation/games.JEUX_DISPONIBLES). */
const MINI_JEUX: { id: string; label: string; emoji: string }[] = [
  { id: "deux_verites", label: "Deux vérités, un mensonge", emoji: "🤥" },
  { id: "action_verite", label: "Action ou vérité", emoji: "🎭" },
  { id: "vingt_questions", label: "20 questions", emoji: "❓" },
];

export function ChatPanel({
  messages,
  typing,
  busy,
  status,
  characterName,
  canRequestPhoto,
  game,
  voix,
  voixActive,
  onSend,
  onPhotoRequest,
  onGameStart,
}: {
  messages: ChatMessage[];
  typing: boolean;
  busy: boolean;
  status: string;
  characterName: string;
  canRequestPhoto: boolean;
  game: GameInfo | null;
  voix?: ProfilVoix;
  voixActive: boolean;
  onSend: (text: string) => void;
  onPhotoRequest: (hint?: string) => void;
  onGameStart: (game: string) => void;
}) {
  const [text, setText] = useState("");
  const [menuJeux, setMenuJeux] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const isDisabled = typing || busy;

  // Défilement du fil uniquement — jamais de scrollIntoView, qui remonterait
  // aussi les ancêtres (fenêtre comprise) et décalerait toute l'app.
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, typing, status]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t || isDisabled) return;
    onSend(t);
    setText("");
  }

  // 📷 : si une demande est écrite dans le champ, elle sert de consigne
  // pour la photo (et le champ est vidé) ; sinon photo de la scène en cours.
  function requestPhoto() {
    const t = text.trim();
    setText("");
    onPhotoRequest(t || undefined);
  }

  // 🎲 : lance le mini-jeu choisi (le serveur confirme par son propre
  // événement game, le refus éventuel arrive en info).
  function lancerJeu(id: string) {
    setMenuJeux(false);
    onGameStart(id);
  }

  function reponseRapide(chip: string) {
    if (isDisabled) return;
    onSend(chip);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Fil de messages */}
      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            m={m}
            characterName={characterName}
            voix={voix}
            voixActive={voixActive}
          />
        ))}
        {typing && (
          <div className="flex items-center gap-1.5 px-2 text-rose-300/60">
            <Dot delay="0ms" />
            <Dot delay="150ms" />
            <Dot delay="300ms" />
            {status && <span className="ml-2 text-xs italic">{status}</span>}
          </div>
        )}
        {!typing && status && (
          <p className="px-2 text-xs italic text-fuchsia-300/60">{status}</p>
        )}
      </div>

      {/* Réponses rapides du mini-jeu en cours */}
      {game && (
        <div className="flex flex-wrap items-center gap-2 border-t border-rose-900/40 bg-[#24101c]/80 px-3 py-2">
          <span className="text-xs font-medium text-fuchsia-300/80">🎲 {game.label}</span>
          {game.chips.map((chip) => (
            <button
              key={chip}
              type="button"
              disabled={isDisabled}
              onClick={() => reponseRapide(chip)}
              className="rounded-full border border-fuchsia-700/60 bg-fuchsia-950/40 px-3 py-1 text-xs font-medium text-fuchsia-100 transition hover:bg-fuchsia-900/60 disabled:opacity-30"
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      {/* Saisie */}
      <form
        onSubmit={submit}
        className="pb-safe-area flex items-center gap-2 border-t border-rose-900/40 bg-[#24101c]/60 p-3"
      >
        <div className="relative shrink-0">
          <button
            type="button"
            onClick={() => setMenuJeux((v) => !v)}
            disabled={isDisabled}
            title="Lancer un mini-jeu — deux vérités un mensonge, action ou vérité, 20 questions"
            className="rounded-full border border-rose-800/60 p-2.5 text-lg transition hover:bg-rose-900/40 disabled:cursor-not-allowed disabled:opacity-30"
          >
            🎲
          </button>
          {menuJeux && (
            <>
              <button
                type="button"
                aria-label="Fermer"
                onClick={() => setMenuJeux(false)}
                className="fixed inset-0 z-20 cursor-default"
              />
              <div className="absolute bottom-full left-0 z-30 mb-2 w-64 overflow-hidden rounded-xl border border-rose-800/60 bg-[#1a0b14] shadow-2xl">
                {MINI_JEUX.map((j) => (
                  <button
                    key={j.id}
                    type="button"
                    onClick={() => lancerJeu(j.id)}
                    className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-rose-100 transition hover:bg-rose-900/50"
                  >
                    <span>{j.emoji}</span> {j.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
        <button
          type="button"
          onClick={requestPhoto}
          disabled={!canRequestPhoto || isDisabled}
          title={
            canRequestPhoto
              ? "Demander une photo — écris ta demande dans le champ pour la préciser (ex : « assise à table face à moi »)"
              : "Débloquez le stade « Neutre » pour demander des photos"
          }
          className="shrink-0 rounded-full border border-rose-800/60 p-2.5 text-lg transition hover:bg-rose-900/40 disabled:cursor-not-allowed disabled:opacity-30"
        >
          📷
        </button>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={isDisabled ? "L'IA réfléchit…" : `Écrire à ${characterName}…`}
          disabled={isDisabled}
          maxLength={2000}
          title="2000 caractères maximum, comme sur une vraie messagerie"
          className="min-w-0 flex-1 rounded-full border border-rose-900/50 bg-[#1a0b14] px-4 py-2.5 text-sm text-rose-50 outline-none transition focus:border-rose-500 disabled:opacity-40"
        />
        <button
          type="submit"
          disabled={!text.trim() || isDisabled}
          className="shrink-0 rounded-full bg-gradient-to-r from-rose-500 to-fuchsia-500 px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-40"
        >
          Envoyer
        </button>
      </form>
    </div>
  );
}

function MessageBubble({
  m,
  characterName,
  voix,
  voixActive,
}: {
  m: ChatMessage;
  characterName: string;
  voix?: ProfilVoix;
  voixActive: boolean;
}) {
  const [lecture, setLecture] = useState(false);

  function ecouter() {
    if (lecture) {
      arreterVoix();
      setLecture(false);
      return;
    }
    parler(m.content, voix, () => setLecture(false));
    setLecture(true);
  }

  if (m.role === "info") {
    return (
      <p className="mx-auto w-fit max-w-[90%] rounded-full bg-fuchsia-950/40 px-4 py-1.5 text-center text-xs italic text-fuchsia-200/70">
        {m.content}
      </p>
    );
  }
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div
          className="max-w-[80%] rounded-2xl rounded-br-md bg-gradient-to-br from-rose-500 to-fuchsia-600 px-4 py-2.5 text-sm text-white shadow"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
        />
      </div>
    );
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-bl-md border border-rose-900/40 bg-[#331627]/80 px-4 py-2.5 text-sm text-rose-50">
        {m.image && (
          <figure className="mb-2">
            <img src={m.image} alt={m.caption || "photo"} className="max-h-72 rounded-xl object-cover" />
            {m.caption && <figcaption className="mt-1 text-center text-xs text-rose-200/50">{m.caption}</figcaption>}
          </figure>
        )}
        <div
          className="[&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
        />
        {!m.streaming && m.content && (
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="sr-only">{characterName} a répondu</span>
            {voixActive && voixDisponible() && (
              <button
                type="button"
                onClick={ecouter}
                title={lecture ? "Arrêter la lecture" : "Écouter le message"}
                className="rounded-full px-1.5 py-0.5 text-xs text-rose-200/50 transition hover:bg-rose-900/40 hover:text-rose-200"
              >
                {lecture ? "⏹" : "🔊"}
              </button>
            )}
          </div>
        )}
        {m.streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-rose-300 align-middle" />}
      </div>
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="inline-block h-2 w-2 animate-bounce rounded-full bg-rose-400/70"
      style={{ animationDelay: delay }}
    />
  );
}
