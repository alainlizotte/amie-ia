// Client REST — fetch typé vers l'API FastAPI (/api proxifié en dev).

import type { PhotoEntry, PresetCharacter, PublicProfile, SessionSummary } from "./types";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
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

export async function apiLogin(nom: string, motDePasse: string): Promise<{ ok: boolean; user: string; nouveau: boolean }> {
  const res = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nom, mot_de_passe: motDePasse }),
  });
  return jsonOrThrow(res);
}

export async function apiPresets(): Promise<{ characters: PresetCharacter[] }> {
  const res = await fetch("/api/presets");
  return jsonOrThrow(res);
}

export async function apiSessions(user: string): Promise<{ sessions: SessionSummary[] }> {
  const res = await fetch(`/api/sessions?user=${encodeURIComponent(user)}`);
  return jsonOrThrow(res);
}

export interface CreateSessionPayload {
  user: string;
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
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return jsonOrThrow(res);
}

export async function apiSession(sid: string, user: string): Promise<PublicProfile> {
  const res = await fetch(`/api/sessions/${sid}?user=${encodeURIComponent(user)}`);
  return jsonOrThrow(res);
}

export async function apiDeleteSession(sid: string, user: string): Promise<void> {
  const res = await fetch(`/api/sessions/${sid}?user=${encodeURIComponent(user)}`, {
    method: "DELETE",
  });
  await jsonOrThrow(res);
}

export async function apiPhotos(sid: string, user: string): Promise<{ photos: PhotoEntry[] }> {
  const res = await fetch(`/api/sessions/${sid}/photos?user=${encodeURIComponent(user)}`);
  return jsonOrThrow(res);
}
