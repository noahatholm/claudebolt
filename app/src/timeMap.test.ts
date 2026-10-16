import { describe, expect, it } from "vitest";
import { playbackAction } from "./playback";
import { outputToSource, segmentAt, sourceToOutput } from "./timeMap";
import type { Seg } from "./types";

const seg = (a: number, b: number, op: Seg["op"], speed?: number): Seg => ({
  src_start: a, src_end: b, out_start: 0, out_end: 0, op, reason: null, locked: false, speed,
});
const segs = [seg(0, 2, "keep"), seg(2, 4, "remove"), seg(4, 6, "speed", 2), seg(6, 8, "keep")];

describe("time mapping", () => {
  it("maps source to output", () => {
    expect(sourceToOutput(segs, 1)).toBe(1);
    expect(sourceToOutput(segs, 3)).toBe(2);
    expect(sourceToOutput(segs, 5)).toBe(2.5);
    expect(sourceToOutput(segs, 7)).toBe(4);
  });
  it("maps output to source", () => {
    expect(outputToSource(segs, 2.5)).toBeCloseTo(5);
    expect(outputToSource(segs, 3.5)).toBeCloseTo(6.5);
    expect(outputToSource(segs, 99)).toBe(8);
  });
  it("finds the segment under the playhead", () => {
    expect(segmentAt(segs, 3)?.op).toBe("remove");
    expect(segmentAt(segs, 0)?.op).toBe("keep");
    expect(segmentAt(segs, 9)).toBeUndefined();
  });
});

describe("edited playback", () => {
  it("skips removed spans", () => {
    expect(playbackAction(segs, 2.5).seekTo).toBe(4);
  });
  it("speeds through speed spans and can mute them", () => {
    expect(playbackAction(segs, 5)).toEqual({ rate: 2, muted: false });
    expect(playbackAction(segs, 5, true).muted).toBe(true);
  });
  it("plays kept spans normally", () => {
    expect(playbackAction(segs, 1)).toEqual({ rate: 1, muted: false });
  });
});
