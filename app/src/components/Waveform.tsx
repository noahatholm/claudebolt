import { useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.esm.js";
import { useStore } from "../store";

const COLORS: Record<string, string> = {
  silence: "rgba(239,68,68,0.35)",
  filler: "rgba(249,115,22,0.45)",
  false_start: "rgba(234,179,8,0.45)",
  retake: "rgba(168,85,247,0.45)",
  manual: "rgba(239,68,68,0.45)",
  agent: "rgba(20,184,166,0.45)",
};

interface Props {
  media: HTMLMediaElement | null;
  duration: number;
}

/** Waveform from engine-supplied peaks (instant on long files), with editable removed/speed regions. */
export function Waveform({ media, duration }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const regions = useRef<RegionsPlugin | null>(null);
  const known = useRef(new Map<string, { a: number; b: number }>());
  const peaks = useStore((s) => s.peaks);
  const segments = useStore((s) => s.segments);
  const edit = useStore((s) => s.edit);

  useEffect(() => {
    if (!el.current || !peaks || !media) return;
    const flat = new Float32Array(peaks.length * 2);
    peaks.forEach((p, i) => {
      flat[i * 2] = p[0];
      flat[i * 2 + 1] = p[1];
    });
    const rp = RegionsPlugin.create();
    const w = WaveSurfer.create({
      container: el.current,
      media,
      peaks: [flat],
      duration,
      height: 120,
      waveColor: "#64748b",
      progressColor: "#38bdf8",
      cursorColor: "#f8fafc",
      normalize: false,
      minPxPerSec: 0,
      plugins: [rp],
    });
    ws.current = w;
    regions.current = rp;

    rp.on("region-updated", (r: Region) => {
      const old = known.current.get(r.id);
      if (!old) return;
      const ops: object[] = [{ action: "keep", start: old.a, end: old.b }];
      ops.push({ action: "remove", start: r.start, end: r.end });
      void edit(ops);
    });
    rp.on("region-clicked", (r: Region, e: MouseEvent) => {
      e.stopPropagation();
      const old = known.current.get(r.id);
      if (old) void edit([{ action: "keep", start: old.a, end: old.b }]);
    });
    return () => {
      w.destroy();
      ws.current = null;
      regions.current = null;
    };
  }, [peaks, media, duration, edit]);

  useEffect(() => {
    const rp = regions.current;
    if (!rp) return;
    rp.clearRegions();
    known.current.clear();
    segments.forEach((s, i) => {
      if (s.op === "keep") return;
      const id = `r${i}`;
      known.current.set(id, { a: s.src_start, b: s.src_end });
      rp.addRegion({
        id,
        start: s.src_start,
        end: s.src_end,
        color: s.op === "speed" ? "rgba(59,130,246,0.35)" : COLORS[s.reason ?? "silence"] ?? COLORS.silence,
        drag: false,
        resize: s.op === "remove" && !s.locked,
      });
    });
  }, [segments, peaks, media]);

  return <div ref={el} className="waveform" />;
}
