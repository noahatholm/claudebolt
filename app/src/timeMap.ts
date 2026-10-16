import type { Seg } from "./types";

const outDur = (s: Seg) => (s.op === "remove" ? 0 : (s.src_end - s.src_start) / (s.op === "speed" ? s.speed ?? 1 : 1));

/** Source time -> edited-output time (removed spans collapse to a point). */
export function sourceToOutput(segs: Seg[], t: number): number {
  let acc = 0;
  for (const s of segs) {
    if (t <= s.src_end + 1e-9) {
      if (t <= s.src_start || s.op === "remove") return acc;
      return acc + (t - s.src_start) / (s.op === "speed" ? s.speed ?? 1 : 1);
    }
    acc += outDur(s);
  }
  return acc;
}

/** Edited-output time -> source time. */
export function outputToSource(segs: Seg[], t: number): number {
  let acc = 0;
  for (const s of segs) {
    const d = outDur(s);
    if (d > 0 && t < acc + d) return s.src_start + (t - acc) * (s.op === "speed" ? s.speed ?? 1 : 1);
    acc += d;
  }
  return segs.length ? segs[segs.length - 1].src_end : 0;
}

export function segmentAt(segs: Seg[], t: number): Seg | undefined {
  let lo = 0;
  let hi = segs.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const s = segs[mid];
    if (t < s.src_start) hi = mid - 1;
    else if (t >= s.src_end) lo = mid + 1;
    else return s;
  }
  return undefined;
}

export function fmt(t: number): string {
  if (!isFinite(t)) return "0:00.0";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}
