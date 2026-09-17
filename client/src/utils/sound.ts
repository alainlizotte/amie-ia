let ctx: AudioContext | null = null;

function getCtx(): AudioContext | null {
  try {
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AC) return null;
    if (!ctx) ctx = new AC();
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

export function playMessageSound() {
  const ac = getCtx();
  if (!ac) return;
  const now = ac.currentTime;
  const master = ac.createGain();
  master.gain.value = 0.15;
  master.connect(ac.destination);

  const notes: Array<[number, number]> = [
    [880, 0],
    [1174.66, 0.12],
  ];

  for (const [freq, offset] of notes) {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    const t0 = now + offset;
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(1, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.35);
    osc.connect(gain);
    gain.connect(master);
    osc.start(t0);
    osc.stop(t0 + 0.4);
  }
}
