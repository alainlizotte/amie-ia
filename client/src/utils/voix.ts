// Synthèse vocale des messages du personnage — Web Speech API (voix du
// système/OS, locale, aucune donnée envoyée sur Internet). Le profil vocal
// du personnage (genre, pitch, rate — calculé côté serveur depuis sa fiche)
// oriente le choix de la voix et sa coloration : chaque personnage sonne
// différemment.

export interface ProfilVoix {
  genre: string; // "femme" | "homme"
  pitch: number; // 0.8 – 1.2
  rate: number; // 0.8 – 1.2
}

// Indices de genre dans les noms des voix système (francophones d'abord).
let _FEMMES: string[] = [
  "amelie", "amélie", "audrey", "virginie", "julie", "marie", "chantal",
  "caroline", "celine", "céline", "charlotte", "hortense", "jessica",
  "female", "femme", "samantha", "zira", "flo", "denise", "serena",
  "sylvie", "aurelie", "aurélie",
];
let _HOMMES: string[] = [
  "thomas", "nicolas", "paul", "henri", "daniel", "guillaume", "claude",
  "male", "homme", "david", "mark", "george", "jerome", "jérôme",
];

let voixFemme: SpeechSynthesisVoice | null = null;
let voixHomme: SpeechSynthesisVoice | null = null;
let voixScannees = false;

function scannerVoix(): void {
  if (voixScannees || typeof speechSynthesis === "undefined") return;
  const toutes = speechSynthesis.getVoices();
  if (!toutes.length) return; // chargement asynchrone — retenter plus tard
  const fr = toutes.filter((v) => v.lang.toLowerCase().startsWith("fr"));
  const candidates = fr.length ? fr : toutes;
  const trouve = (indices: string[]) =>
    candidates.find((v) => {
      const nom = v.name.toLowerCase();
      return indices.some((i) => nom.includes(i));
    }) ?? null;
  voixFemme = trouve(_FEMMES) ?? candidates[0] ?? null;
  voixHomme = trouve(_HOMMES) ?? candidates[candidates.length > 1 ? 1 : 0] ?? null;
  if (voixHomme === voixFemme && candidates.length < 2) voixHomme = voixFemme;
  voixScannees = true;
}

// Les voix se chargent souvent APRÈS le premier appel : on rescanner tant
// que rien n'est disponible.
if (typeof speechSynthesis !== "undefined") {
  speechSynthesis.onvoiceschanged = () => {
    voixScannees = false;
    scannerVoix();
  };
}

/** Nettoie un texto pour la lecture : markdown, emojis, échos techniques. */
export function nettoyerPourVoix(texte: string): string {
  return (texte || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[*_`~>#|]/g, " ")
    .replace(/\[(.*?)\]\(.*?\)/g, "$1")
    // Emojis et symboles décoratifs : la synthèse les énonce sinon.
    .replace(
      /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}\u{2B00}-\u{2BFF}\u{20E3}]/gu,
      " ",
    )
    .replace(/https?:\S+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function voixDisponible(): boolean {
  return typeof speechSynthesis !== "undefined" && "SpeechSynthesisUtterance" in window;
}

/** Énonce un texte avec la voix correspondant au personnage. */
export function parler(
  texte: string,
  profil?: ProfilVoix,
  onFin?: () => void,
): void {
  if (!voixDisponible()) return;
  const brut = nettoyerPourVoix(texte);
  if (!brut) return;
  arreterVoix();
  scannerVoix();
  const utter = new SpeechSynthesisUtterance(brut);
  const veutFemme = (profil?.genre ?? "femme") === "femme";
  scannerVoix();
  const voix = veutFemme ? voixFemme : (voixHomme ?? voixFemme);
  if (voix) utter.voice = voix;
  utter.lang = voix?.lang?.startsWith("fr") ? voix.lang : "fr-FR";
  utter.pitch = Math.min(2, Math.max(0.5, profil?.pitch ?? 1));
  utter.rate = Math.min(2, Math.max(0.5, profil?.rate ?? 1));
  if (onFin) {
    utter.onend = () => onFin();
    utter.onerror = () => onFin();
  }
  speechSynthesis.speak(utter);
}

/** Coupe la lecture en cours. */
export function arreterVoix(): void {
  if (voixDisponible()) speechSynthesis.cancel();
}
