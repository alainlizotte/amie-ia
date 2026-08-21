// Store Zustand central — fil de discussion, profil relationnel, état WS.
// Accumulateur des événements WebSocket (delta streaming, dm final,
// tool_event images, mises à jour de score).

import { create } from "zustand";
import type { ChatMessage, PublicProfile } from "./api/types";

const USER_KEY = "amie.user";
const PASSWORD_KEY = "amie.password";

function initialUser(): string {
  try {
    return localStorage.getItem(USER_KEY) || "";
  } catch {
    return "";
  }
}

/** Mot de passe en sessionStorage : survit au rechargement de l'onglet
 *  (le WS doit pouvoir se ré-authentifier) mais pas à la fermeture. */
function initialPassword(): string {
  try {
    return sessionStorage.getItem(PASSWORD_KEY) || "";
  } catch {
    return "";
  }
}

interface AmieStore {
  // -- Compte ------------------------------------------------------------- //
  user: string;
  password: string;
  setUser: (u: string) => void;
  setPassword: (p: string) => void;

  // -- Session courante --------------------------------------------------- //
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  joined: boolean;
  setJoined: (v: boolean) => void;
  authError: string | null;
  setAuthError: (e: string | null) => void;

  // -- Profil relationnel (miroir du serveur) ------------------------------ //
  profile: PublicProfile | null;
  setProfile: (p: PublicProfile) => void;
  patchProfile: (patch: Partial<PublicProfile>) => void;

  // -- Fil de discussion --------------------------------------------------- //
  messages: ChatMessage[];
  typing: boolean;
  status: string;
  setTyping: (v: boolean) => void;
  setStatus: (s: string) => void;

  addMessage: (m: ChatMessage) => void;
  beginStream: () => string;
  appendDelta: (streamId: string, text: string) => void;
  endStream: (streamId: string, finalText?: string) => void;

  reset: () => void;
}

const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

export const useAmie = create<AmieStore>((set) => ({
  user: initialUser(),
  password: initialPassword(),
  setUser: (u) => {
    set({ user: u });
    try {
      if (u) localStorage.setItem(USER_KEY, u);
      else localStorage.removeItem(USER_KEY);
    } catch {
      /* localStorage indisponible */
    }
  },
  setPassword: (p) => {
    set({ password: p });
    try {
      if (p) sessionStorage.setItem(PASSWORD_KEY, p);
      else sessionStorage.removeItem(PASSWORD_KEY);
    } catch {
      /* sessionStorage indisponible */
    }
  },

  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),
  joined: false,
  setJoined: (v) => set({ joined: v }),
  authError: null,
  setAuthError: (e) => set({ authError: e }),

  profile: null,
  setProfile: (p) => set({ profile: p }),
  patchProfile: (patch) =>
    set((st) => (st.profile ? { profile: { ...st.profile, ...patch } } : st)),

  messages: [],
  typing: false,
  status: "",
  setTyping: (v) => set({ typing: v }),
  setStatus: (s) => set({ status: s }),

  addMessage: (m) => set((st) => ({ messages: [...st.messages, m] })),

  /** Crée la bulle assistant en cours de streaming ; renvoie son id. */
  beginStream: () => {
    const id = uid();
    set((st) => ({
      messages: [...st.messages, { id, role: "assistant", content: "", streaming: true }],
    }));
    return id;
  },

  appendDelta: (streamId, text) =>
    set((st) => ({
      messages: st.messages.map((m) =>
        m.id === streamId ? { ...m, content: m.content + text } : m,
      ),
    })),

  endStream: (streamId, finalText) =>
    set((st) => ({
      messages: st.messages.map((m) =>
        m.id === streamId
          ? { ...m, content: finalText ?? m.content, streaming: false }
          : m,
      ),
    })),

  // Conserve user/password : ce sont des choix de session navigateur.
  reset: () =>
    set({
      sessionId: null,
      joined: false,
      authError: null,
      profile: null,
      messages: [],
      typing: false,
      status: "",
    }),
}));

export { uid };
