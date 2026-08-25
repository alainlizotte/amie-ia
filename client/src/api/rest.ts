// Client REST — fetch typé vers l'API FastAPI (/api proxifié en dev).
// Auth par token Bearer : le token est mémorisé dans localStorage et injecté
// dans chaque requête ; un 401 déclenche la déconnexion forcée côté UI
// (callback onNonAuthentifie).

import type { PhotoEntry, PresetCharacter, PublicProfile, SessionSummary } from "./types";

const API = "/api";
const TOKEN_KEY = "amie.token";

// --------------------------------------------------------------------------- //
//  Token — gestion locale + déconnexion forcée sur 401.
// --------------------------------------------------------------------------- //
let surNonAuthentifie: (() => void) | null = null;

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* localStorage indisponible */
  }
}

/** Callback invoqué sur 401 (déconnexion forcée côté UI). */
export function onNonAuthentifie(cb: () => void): void {
  surNonAuthentifie = cb;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    // Session expirée → déconnexion propre (sauf sur les routes auth).
    if (res.status === 401 && !res.url.includes("/api/auth/")) {
      setToken("");
      surNonAuthentifie?.();
    }
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* corps non JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

function entetes(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...(extra ?? {}) };
  const token = getToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

// --------------------------------------------------------------------------- //
//  Auth — inscription / connexion / identité.
// --------------------------------------------------------------------------- //
export interface AuthReponse {
  token: string;
  utilisateur: string;
}

export async function apiInscription(nom: string, motDePasse: string): Promise<AuthReponse> {
  const res = await fetch(`${API}/auth/inscription`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nom, mot_de_passe: motDePasse }),
  });
  return jsonOrThrow(res);
}

export async function apiConnexion(nom: string, motDePasse: string): Promise<AuthReponse> {
  const res = await fetch(`${API}/auth/connexion`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nom, mot_de_passe: motDePasse }),
  });
  return jsonOrThrow(res);
}

export async function apiMoi(): Promise<{ utilisateur: string }> {
  const res = await fetch(`${API}/auth/moi`, { headers: entetes() });
  return jsonOrThrow(res);
}

// --------------------------------------------------------------------------- //
//  Sessions de rencontre.
// --------------------------------------------------------------------------- //
export async function apiPresets(): Promise<{ characters: PresetCharacter[] }> {
  const res = await fetch(`${API}/presets`);
  return jsonOrThrow(res);
}

export async function apiSessions(): Promise<{ sessions: SessionSummary[] }> {
  const res = await fetch(`${API}/sessions`, { headers: entetes() });
  return jsonOrThrow(res);
}

export interface CreateSessionPayload {
  preset_id?: string;
  character?: {
    name: string;
    age?: string;
    title?: string;
    gender?: string;
    occupation?: string;
    interests?: string;
    appearance?: string;
    personality?: string;
  };
  user_info?: { name?: string; preferences?: string };
}

export async function apiCreateSession(
  payload: CreateSessionPayload,
): Promise<{ ok: boolean; session_id: string; profile: PublicProfile }> {
  const res = await fetch(`${API}/sessions`, {
    method: "POST",
    headers: entetes({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return jsonOrThrow(res);
}

export async function apiSession(sid: string): Promise<PublicProfile> {
  const res = await fetch(`${API}/sessions/${encodeURIComponent(sid)}`, {
    headers: entetes(),
  });
  return jsonOrThrow(res);
}

export async function apiDeleteSession(sid: string): Promise<void> {
  const res = await fetch(`${API}/sessions/${encodeURIComponent(sid)}`, {
    method: "DELETE",
    headers: entetes(),
  });
  await jsonOrThrow(res);
}

export async function apiPhotos(sid: string): Promise<{ photos: PhotoEntry[] }> {
  const res = await fetch(
    `${API}/sessions/${encodeURIComponent(sid)}/photos`,
    { headers: entetes() },
  );
  return jsonOrThrow(res);
}
