// Client WebSocket — une seule connexion persistante par session de rencontre.
// Reconnexion automatique avec backoff exponentiel (1s → 5s plafonné),
// comme le projet D&D. Le join porte nom + mot de passe (auth serveur).
//
// Important : les messages envoyés pendant que le socket n'est pas encore
// OPEN (état CONNECTING après new WebSocket) sont mis en file et expédiés
// à l'ouverture — sinon le join initial est perdu et l'UI reste bloquée
// sur « Connexion… ». À la reconnexion, le join est renvoyé automatiquement.

import type { WsInMessage, WsOutMessage } from "./types";

export type WsHandler = (msg: WsInMessage) => void;

export class ChatSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers = new Set<WsHandler>();
  private retries = 0;
  private manualClose = false;
  private openedOnce = false;
  private queue: WsOutMessage[] = [];
  private lastJoin: { user: string; password: string } | null = null;

  constructor(sessionId: string) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    // En dev Vite (5174), le proxy /ws route vers 8000 ; en prod, même origine.
    this.url = `${proto}//${window.location.host}/ws/${sessionId}`;
  }

  on(h: WsHandler): () => void {
    this.handlers.add(h);
    return () => this.handlers.delete(h);
  }

  connect(): void {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return; // déjà active
    this.manualClose = false;
    const wasConnectedBefore = this.openedOnce;
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => {
      this.retries = 0;
      // Reconnexion : on se ré-authentifie d'abord (le serveur a perdu
      // l'association join ↔ socket), puis on vide la file.
      if (wasConnectedBefore && this.lastJoin) {
        this.rawSend({ type: "join", ...this.lastJoin });
      }
      const pending = this.queue.splice(0);
      for (const p of pending) this.rawSend(p);
      this.openedOnce = true;
    };
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as WsInMessage;
        this.handlers.forEach((h) => h(msg));
      } catch {
        /* payload non JSON — ignoré */
      }
    };
    this.ws.onclose = () => {
      if (this.manualClose) return;
      const delay = Math.min(1000 * 2 ** this.retries, 5000);
      this.retries += 1;
      setTimeout(() => this.connect(), delay);
    };
    this.ws.onerror = () => this.ws?.close();
  }

  private rawSend(payload: WsOutMessage): void {
    try {
      this.ws?.send(JSON.stringify(payload));
      this.retries = 0; // un envoi réussi réinitialise le backoff.
    } catch {
      /* socket fermée entre-temps : la reconnexion repartira */
    }
  }

  send(payload: WsOutMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.rawSend(payload);
    } else {
      // CONNECTING ou CLOSED : mise en file, envoi à la prochaine ouverture.
      this.queue.push(payload);
    }
  }

  join(user: string, password: string): void {
    this.lastJoin = { user, password };
    this.send({ type: "join", user, password });
  }

  say(text: string): void {
    this.send({ type: "say", text });
  }

  photoRequest(hint?: string): void {
    this.send({ type: "photo_request", hint });
  }

  close(): void {
    this.manualClose = true;
    this.ws?.close();
    this.ws = null;
  }
}
