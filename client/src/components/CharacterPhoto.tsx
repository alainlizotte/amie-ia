// Photo du personnage — affichée en permanence dans le panneau latéral.
// Placeholder élégant tant que le portrait n'est pas généré.

export function CharacterPhoto({
  url,
  name,
  gender,
  pending,
}: {
  url: string | null;
  name: string;
  gender: string;
  pending?: boolean;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-rose-900/40 bg-[#1a0b14]">
      <div className="aspect-[3/4] w-full">
        {url ? (
          <img src={url} alt={name} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-rose-200/30">
            <span className="text-5xl">{gender === "M" ? "👨" : "👩"}</span>
            <span className="text-xs">{pending ? "Photo en préparation…" : "Pas encore de photo"}</span>
          </div>
        )}
      </div>
      {url && (
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-3">
          <p className="text-sm font-semibold text-white drop-shadow">{name}</p>
        </div>
      )}
    </div>
  );
}
