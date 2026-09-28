// Son de notification — joue un ding quand le personnage envoie un message.
//
// Bug beta : le son « ne fonctionnait pas ». En réalité il était déclenché
// (oscillateurs créés) mais quasi inaudible : gain master 0.15, deux sinus
// purs de 0,35 s sans harmoniques. De plus, l'AudioContext n'était créé qu'à
// l'arrivée du premier message : selon la politique autoplay du navigateur,
// il pouvait démarrer « suspended » et rester muet jusqu'à un geste.
//
// Corrections :
// - volume maître relevé + enveloppe plus franche (attaque rapide, tenue) ;
// - timbre enrichi (harmonique en triangle) pour un ding perceptible ;
// - le contexte est armé au PREMIER geste utilisateur (clic/touche) via
//   armAudio(), appelé au montage de l'app — le contexte est alors déjà
//   « running » quand le premier message arrive.

let ctx: AudioContext | null = null;
let arme = false;

function getCtx(): AudioContext | null {
  try {
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AC) return null;
    if (!ctx) ctx = new AC();
    return ctx;
  } catch {
    return null;
  }
}

/** Force la reprise du contexte si le navigateur l'a suspendu. */
async function assurerActif(ac: AudioContext): Promise<boolean> {
  if (ac.state === "running") return true;
  try {
    await ac.resume();
  } catch {
    return false;
  }
  // resume() mute l'état côté navigateur ; on relit via une variable
  // typée string pour éviter le narrowing TS (state ≠ "running" vus du
  // compilateur avant l'appel).
  const etat: string = ac.state;
  return etat === "running";
}

/**
 * À appeler une fois au montage de l'app : crée et réveille l'AudioContext
 * dès le premier geste utilisateur (les navigateurs exigent un geste pour
 * autoriser la sortie audio — le faire tôt garantit que le ding du premier
 * message du personnage est audible).
 */
export function armAudio(): void {
  if (arme) return;
  const installer = () => {
    if (arme) return;
    arme = true;
    const ac = getCtx();
    if (ac) void assurerActif(ac);
    window.removeEventListener("pointerdown", installer);
    window.removeEventListener("keydown", installer);
    window.removeEventListener("touchstart", installer);
  };
  window.addEventListener("pointerdown", installer, { once: false });
  window.addEventListener("keydown", installer, { once: false });
  window.addEventListener("touchstart", installer, { once: false });
}

export function playMessageSound() {
  const ac = getCtx();
  if (!ac) return;

  // Contexte suspendu (onglet réveillé, politique autoplay…) : on tente la
  // reprise ; si elle échoue, inutile de planifier des notes muettes.
  if (ac.state !== "running") {
    void assurerActif(ac).then((actif) => {
      if (actif) playMessageSound();
    });
    return;
  }

  const now = ac.currentTime;
  const master = ac.createGain();
  master.gain.value = 0.5;
  master.connect(ac.destination);

  // Ding « notification » : quinte montante avec harmonique en triangle.
  // [fréquence, début(s), durée(s), gain relatif]
  const notes: Array<[number, number, number, number]> = [
    [880, 0, 0.28, 1.0], // La5 — corps du ding
    [1318.51, 0.09, 0.3, 0.7], // Mi6 — éclat
  ];

  for (const [freq, offset, duree, niveau] of notes) {
    // Fondamentale (sine) + harmonique (triangle, une octave au-dessus) :
    // sine seul est trop doux pour être remarqué.
    for (const [type, mult, vol] of [
      ["sine", 1, 1],
      ["triangle", 2, 0.25],
    ] as Array<[OscillatorType, number, number]>) {
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = type;
      osc.frequency.value = freq * mult;
      const t0 = now + offset;
      gain.gain.setValueAtTime(0.0001, t0);
      gain.gain.exponentialRampToValueAtTime(niveau * vol, t0 + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duree);
      osc.connect(gain);
      gain.connect(master);
      osc.start(t0);
      osc.stop(t0 + duree + 0.05);
    }
  }
}
