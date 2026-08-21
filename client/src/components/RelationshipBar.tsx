// Barre de relation — score + stade courant (miroir des stades serveur).

import { STAGE_LABELS, STAGE_THRESHOLDS } from "../api/types";

const STAGE_ORDER = ["rejet", "froid", "reserve", "neutre", "chaleureux", "proche"];

export function RelationshipBar({
  score,
  stage,
}: {
  score: number;
  stage: string;
}) {
  const idx = STAGE_ORDER.indexOf(stage);
  const nextStage = STAGE_ORDER[idx + 1];
  const floor = STAGE_THRESHOLDS[stage] ?? 0;
  const ceil = nextStage ? STAGE_THRESHOLDS[nextStage] : 1000;
  const pct = Math.min(100, Math.max(0, ((score - floor) / (ceil - floor)) * 100));

  return (
    <div className="w-full">
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="font-medium text-fuchsia-300">
          {STAGE_LABELS[stage] ?? stage}
        </span>
        <span className="text-rose-200/40">
          {score} pts{nextStage ? ` · prochain stade à ${ceil}` : " · stade maximum 💍"}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[#331627]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-rose-500 to-fuchsia-400 transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
