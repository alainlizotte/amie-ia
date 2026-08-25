// Sélecteur de personnage — grille des presets + formulaire personnalisé.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiCreateSession, apiPresets, type CreateSessionPayload } from "../api/rest";
import type { PresetCharacter } from "../api/types";
import { useAmie } from "../store";

export function CharacterPicker({ onCreated }: { onCreated: (sid: string) => void }) {
  const [mode, setMode] = useState<"preset" | "custom">("preset");
  const [creating, setCreating] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const userName = useAmie((s) => s.profile?.user_info?.name ?? "");

  const { data, isLoading } = useQuery({
    queryKey: ["presets"],
    queryFn: apiPresets,
  });

  async function create(payload: Omit<CreateSessionPayload, "user">) {
    setCreating(true);
    setErreur(null);
    try {
      const res = await apiCreateSession(payload);
      onCreated(res.session_id);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <div className="mb-4 flex gap-2">
        <TabButton active={mode === "preset"} onClick={() => setMode("preset")}>
          Personnages
        </TabButton>
        <TabButton active={mode === "custom"} onClick={() => setMode("custom")}>
          Créer le mien
        </TabButton>
      </div>

      {erreur && (
        <p className="mb-3 rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {erreur}
        </p>
      )}

      {mode === "preset" ? (
        isLoading ? (
          <p className="text-sm text-rose-200/50">Chargement…</p>
        ) : (
          <div className="grid max-h-[55vh] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
            {(data?.characters ?? []).map((c) => (
              <PresetCard key={c.id} c={c} disabled={creating} onClick={() => create({ preset_id: c.id })} />
            ))}
          </div>
        )
      ) : (
        <CustomForm disabled={creating} onSubmit={create} defaultUserName={userName} />
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        active
          ? "rounded-full bg-rose-500/20 px-4 py-1.5 text-sm font-medium text-rose-200 ring-1 ring-rose-500/50"
          : "rounded-full px-4 py-1.5 text-sm text-rose-200/50 transition hover:text-rose-200"
      }
    >
      {children}
    </button>
  );
}

function PresetCard({
  c,
  disabled,
  onClick,
}: {
  c: PresetCharacter;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="group rounded-xl border border-rose-900/40 bg-[#1a0b14] p-4 text-left transition hover:border-rose-500/60 hover:bg-[#331627]/60 disabled:opacity-40"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold text-rose-100">{c.name}</span>
        <span className="text-xs text-rose-200/50">
          {c.age} ans · {c.gender === "F" ? "♀" : "♂"}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-fuchsia-300/70">{c.title}</p>
      <p className="mt-2 line-clamp-2 text-xs text-rose-200/60">{c.personality}</p>
    </button>
  );
}

function CustomForm({
  disabled,
  onSubmit,
  defaultUserName,
}: {
  disabled: boolean;
  onSubmit: (payload: Omit<CreateSessionPayload, "user">) => void;
  defaultUserName: string;
}) {
  const [f, setF] = useState({
    name: "",
    age: "",
    gender: "F",
    title: "",
    occupation: "",
    interests: "",
    appearance: "",
    personality: "",
  });
  const [userName, setUserName] = useState(defaultUserName);
  const [ageErreur, setAgeErreur] = useState<string | null>(null);

  const field =
    "w-full rounded-lg border border-rose-900/50 bg-[#1a0b14] px-3 py-2 text-sm text-rose-50 outline-none focus:border-rose-500";
  const label = "mb-1 block text-xs font-medium text-rose-200/70";

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const age = f.age.trim();
        if (age) {
          const n = Number(age);
          if (!Number.isFinite(n) || n < 18) {
            setAgeErreur("L'âge du personnage doit être d'au moins 18 ans.");
            return;
          }
        }
        setAgeErreur(null);
        onSubmit({
          character: { ...f },
          user_info: { name: userName },
        });
      }}
      className="max-h-[75vh] space-y-3 overflow-y-auto pr-1"
    >
      <div>
        <label className={label}>Votre prénom (dans l'histoire)</label>
        <input
          className={field}
          value={userName}
          onChange={(e) => setUserName(e.target.value)}
          placeholder="comment il/elle vous appelle"
        />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className={label}>Prénom du personnage *</label>
          <input
            className={field}
            value={f.name}
            onChange={(e) => setF({ ...f, name: e.target.value })}
            required
          />
        </div>
        <div>
          <label className={label}>Âge</label>
          <input
            className={field}
            value={f.age}
            onChange={(e) => {
              setF({ ...f, age: e.target.value });
              setAgeErreur(null);
            }}
            inputMode="numeric"
            placeholder="18+"
          />
          {ageErreur && (
            <p className="mt-1 text-xs text-red-300">{ageErreur}</p>
          )}
        </div>
        <div>
          <label className={label}>Genre</label>
          <select
            className={field}
            value={f.gender}
            onChange={(e) => setF({ ...f, gender: e.target.value })}
          >
            <option value="F">Femme</option>
            <option value="M">Homme</option>
          </select>
        </div>
      </div>
      <div>
        <label className={label}>Profession / occupation</label>
        <input
          className={field}
          value={f.occupation}
          onChange={(e) => setF({ ...f, occupation: e.target.value })}
          placeholder="ex : graphiste freelance"
        />
      </div>
      <div>
        <label className={label}>Centres d'intérêt</label>
        <input
          className={field}
          value={f.interests}
          onChange={(e) => setF({ ...f, interests: e.target.value })}
          placeholder="ex : cuisine, randonnée, jeux vidéo"
        />
      </div>
      <div>
        <label className={label}>Apparence (pour la photo)</label>
        <textarea
          className={field}
          rows={2}
          value={f.appearance}
          onChange={(e) => setF({ ...f, appearance: e.target.value })}
          placeholder="ex : cheveux châtains bouclés, yeux verts, sourire malicieux"
        />
      </div>
      <div>
        <label className={label}>Personnalité</label>
        <textarea
          className={field}
          rows={2}
          value={f.personality}
          onChange={(e) => setF({ ...f, personality: e.target.value })}
          placeholder="ex : réservée mais drôle une fois en confiance"
        />
      </div>
      <button
        type="submit"
        disabled={disabled || !f.name.trim()}
        className="w-full rounded-lg bg-gradient-to-r from-rose-500 to-fuchsia-500 py-2.5 font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {disabled ? "Création…" : "Commencer la rencontre"}
      </button>
    </form>
  );
}
