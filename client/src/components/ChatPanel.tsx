// Panneau de chat — fil de messages, saisie, bouton « demander une photo ».

import { useEffect, useRef, useState } from "react";
import { renderMarkdown } from "../utils/markdown";
import type { ChatMessage } from "../api/types";

export function ChatPanel({
  messages,
  typing,
  busy,
  status,
  characterName,
  canRequestPhoto,
  onSend,
  onPhotoRequest,
}: {
  messages: ChatMessage[];
  typing: boolean;
  busy: boolean;
  status: string;
  characterName: string;
  canRequestPhoto: boolean;
  onSend: (text: string) => void;
  onPhotoRequest: (hint?: string) => void;
}) {
  const [text, setText] = useState("");
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Fil de messages */}
      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((m) => (
          <MessageBubble key={m.id} m={m} characterName={characterName} />
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

      {/* Saisie */}
      <form
        onSubmit={submit}
        className="pb-safe-area flex items-center gap-2 border-t border-rose-900/40 bg-[#24101c]/60 p-3"
      >
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

function MessageBubble({ m, characterName }: { m: ChatMessage; characterName: string }) {
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
        {m.streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-rose-300 align-middle" />}
        {!m.streaming && m.content && (
          <span className="sr-only">{characterName} a répondu</span>
        )}
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
