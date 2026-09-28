// Rendu Markdown sécurisé via `marked`. Désactive explicitement HTML inline
// pour éviter l'injection XSS depuis une réponse LLM, et neutralise les URI
// dangereux (javascript:, vbscript:, data:) dans les liens/images produites
// par le markdown — marked n'applique AUCUNE validation de schéma d'URL :
// sans ce filtre, `[clique](javascript:alert(1))` rend un lien exécutable.

import { marked } from "marked";

marked.setOptions({ gfm: true, breaks: true });

// Schémas d'URL interdits dans href/src (XSS, fuite, exécution).
const _SCHEMA_DANGEREUX = /^\s*(javascript|vbscript|data)\s*:/i;

export function renderMarkdown(text: string): string {
  if (!text) return "";
  // marked ne sanitize pas natif ; on échappe les balises HTML avant rendu,
  // puis on parse le markdown restant (**gras**, listes, titres).
  const esc = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const html = marked.parse(esc) as string;
  // marked émet toujours des attributs cités (double ou simple quote).
  // Tout href/src au schéma dangereux devient « # » : lien inoffensif.
  return html.replace(
    /\s(href|src)=(["'])(.*?)\2/g,
    (m, attr: string, _quote: string, url: string) =>
      _SCHEMA_DANGEREUX.test(url) ? ` ${attr}="#"` : m,
  );
}
