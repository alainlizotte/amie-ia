// Hook : câble le ChatSocket au store — un seul endroit gère les messages WS.

import { useEffect, useRef } from "react";
import { ChatSocket } from "../api/ws";
import { uid, useAmie } from "../store";

export function useChatSocket(sid: string | undefined) {
  const socketRef = useRef<ChatSocket | null>(null);
  const store = useAmie;

  useEffect(() => {
    if (!sid) return;
    const socket = new ChatSocket(sid);
    socketRef.current = socket;

    const {
      token,
      setJoined,
      setAuthError,
      setProfile,
      patchProfile,
      addMessage,
      beginStream,
      appendDelta,
      endStream,
      setTyping,
      setBusy,
      setStatus,
    } = store.getState();

    socket.on((msg) => {
      switch (msg.type) {
        case "sys":
          if (msg.event === "joined") {
            setJoined(true);
            setAuthError(null);
            setProfile(msg.profile);
            // Rejoue l'historique persisté (une seule fois par join).
            useAmie.setState((st) => ({
              messages: msg.history.map((h) => ({
                id: uid(),
                role: h.role === "assistant" ? "assistant" : "user",
                content: h.content,
              })),
            }));
          } else if (msg.event === "auth_failed") {
            setAuthError(msg.detail || "Authentification refusée.");
          } else if (msg.event === "busy") {
            setBusy(true);
            addMessage({ id: uid(), role: "info", content: msg.detail || "L'IA est occupée…" });
            setTimeout(() => setBusy(false), 3000);
          }
          break;

        case "player":
          addMessage({ id: uid(), role: "user", content: msg.text });
          break;

        case "typing":
          setTyping(msg.on);
          break;

        case "status":
          setStatus(msg.description);
          break;

        case "delta": {
          // Première delta → ouvre la bulle streaming.
          const streaming = useAmie
            .getState()
            .messages.find((m) => m.streaming && m.role === "assistant");
          const streamId = streaming ? streaming.id : beginStream();
          appendDelta(streamId, msg.text);
          break;
        }

        case "dm": {
          // Finalise la bulle en cours (ou en crée une si deltas manqués).
          const streaming = useAmie
            .getState()
            .messages.find((m) => m.streaming && m.role === "assistant");
          if (streaming) endStream(streaming.id, msg.text);
          else addMessage({ id: uid(), role: "assistant", content: msg.text });
          setBusy(false);
          break;
        }

        case "tool_event":
          if (msg.event.type === "image_ready") {
            addMessage({
              id: uid(),
              role: "assistant",
              content: msg.event.msg,
              image: msg.event.image,
              caption: msg.event.caption,
            });
            patchProfile({ portrait_url: msg.event.image, photos_count: (useAmie.getState().profile?.photos_count ?? 0) + 1 });
          } else if (msg.event.type === "info" || msg.event.type === "error") {
            addMessage({
              id: uid(),
              role: "info",
              content: msg.event.msg,
            });
          }
          // image_pending : indicateur visuel via status.
          else if (msg.event.type === "image_pending") {
            setStatus(msg.event.msg);
          }
          break;

        case "profile":
          patchProfile({
            score: msg.score,
            stage: msg.stage,
            interaction_count: msg.interaction_count,
            events_consumed: msg.events_consumed,
            unanswered_messages: msg.unanswered_messages,
          });
          if (msg.stage_changed) {
            addMessage({
              id: uid(),
              role: "info",
              content: `💗 Votre relation évolue : nouveau stade atteint !`,
            });
          }
          break;
      }
    });

    socket.connect();
    // Auth dès l'ouverture ; en cas d'échec, le serveur répond auth_failed.
    socket.join(token);

    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [sid, store]);

  return socketRef;
}
