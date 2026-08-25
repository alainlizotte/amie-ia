// Types partagés du client Ami(e) IA — miroir des payloads serveur.

export interface CharacterInfo {
  name: string;
  age: string | number;
  title: string;
  gender: string;
  occupation: string;
  interests: string;
  appearance: string;
  personality: string;
  preset_id: string | null;
}

export interface PublicProfile {
  session_id: string;
  titre: string;
  character: CharacterInfo;
  user_info: { name?: string; preferences?: string };
  score: number;
  stage: string;
  interaction_count: number;
  last_interaction: string | null;
  /** Messages spontanés du personnage restés sans réponse (badge « ! »). */
  unanswered_messages: number;
  portrait_url: string | null;
  photos_count: number;
  events_consumed: number;
  events_total: number;
  date_creation: string;
}

export interface SessionSummary extends PublicProfile {
  last_message: string;
}

export interface PresetCharacter {
  id: string;
  name: string;
  age: string | number;
  title: string;
  gender: string;
  personality: string;
  occupation: string;
}

export interface PhotoEntry {
  url: string;
  kind: "portrait" | "photo";
  caption: string;
  ts: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "info";
  content: string;
  image?: string | null;
  caption?: string;
  streaming?: boolean;
}

export type ToolEvent =
  | { type: "image_pending"; msg: string }
  | { type: "image_ready"; kind: string; msg: string; image: string; caption: string }
  | { type: "info"; msg: string }
  | { type: "error"; msg: string };

/** Messages sortants (client → serveur). */
export type WsOutMessage =
  | { type: "join"; token: string }
  | { type: "say"; text: string }
  | { type: "photo_request"; hint?: string };

/** Messages entrants (serveur → client). */
export type WsInMessage =
  | { type: "sys"; event: "joined"; history: { role: string; content: string }[]; profile: PublicProfile }
  | { type: "sys"; event: "auth_failed" | "auth_required" | "error"; detail?: string }
  | { type: "player"; text: string }
  | { type: "status"; description: string; done?: boolean }
  | { type: "typing"; on: boolean }
  | { type: "delta"; text: string }
  | { type: "dm"; text: string }
  | { type: "tool_event"; event: ToolEvent }
  | {
      type: "profile";
      score: number;
      stage: string;
      stage_changed: boolean;
      delta: number;
      interaction_count: number;
      events_consumed: number;
      event_consumed_now: boolean;
      unanswered_messages: number;
    };

/** Libellés des stades relationnels (miroir server/relation/stages.py). */
export const STAGE_LABELS: Record<string, string> = {
  rejet: "Rejet",
  froid: "Froid",
  reserve: "Réservé",
  neutre: "Neutre",
  chaleureux: "Chaleureux",
  proche: "Proche",
};

/** Score minimal pour atteindre chaque stade (miroir compute_stage). */
export const STAGE_THRESHOLDS: Record<string, number> = {
  rejet: 0,
  froid: 100,
  reserve: 200,
  neutre: 400,
  chaleureux: 600,
  proche: 800,
};
