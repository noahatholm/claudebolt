import { segmentAt } from "./timeMap";
import type { Seg } from "./types";

export interface PlayAction {
  seekTo?: number;
  rate: number;
  muted: boolean;
}

/** "Edited" preview: jump over removed spans, speed through speed spans. Cheap, ~1 frame of slop. */
export function playbackAction(segs: Seg[], t: number, muteSpeed = false): PlayAction {
  const s = segmentAt(segs, t);
  if (!s || s.op === "keep") return { rate: 1, muted: false };
  if (s.op === "remove") {
    const next = segs.find((x) => x.src_start >= s.src_end - 1e-9 && x.op !== "remove");
    return { seekTo: next ? next.src_start : s.src_end, rate: 1, muted: false };
  }
  return { rate: Math.min(16, s.speed ?? 1), muted: muteSpeed };
}
