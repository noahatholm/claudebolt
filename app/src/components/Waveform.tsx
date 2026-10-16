import { useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.esm.js";
import { KIND_VAR } from "../kinds";
import { useStore } from "../store";
import { useTheme } from "../theme";

interface Props {
  media: HTMLMediaElement | null;
  duration: number;
}

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function tint(hex: string, a: number) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

const waveColors = () => ({ waveColor: token("--wave"), progressColor: token("--wave-progress"), cursorColor: token("--cursor") });

/** Waveform from engine-supplied peaks (instant on long files), with editable removed/speed regions. */
export function Waveform({ media, duration }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const regions = useRef<RegionsPlugin | null>(null);
  const known = useRef(new Map<string, { a: number; b: number }>());
  const peaks = useStore((s) => s.peaks);
  const segments = useStore((s) => s.segments);
  const edit = useStore((s) => s.edit);
  const theme = useTheme((s) => s.resolved);

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
      height: 104,
      ...waveColors(),
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
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
    ws.current?.setOptions(waveColors());
  }, [theme]);

  useEffect(() => {
    const rp = regions.current;
    if (!rp) return;
    const alpha = theme === "dark" ? 0.24 : 0.2;
    rp.clearRegions();
    known.current.clear();
    segments.forEach((s, i) => {
      if (s.op === "keep") return;
      const id = `r${i}`;
      known.current.set(id, { a: s.src_start, b: s.src_end });
      const kind = s.op === "speed" ? "speed" : s.reason ?? "silence";
      rp.addRegion({
        id,
        start: s.src_start,
        end: s.src_end,
        color: tint(token(KIND_VAR[kind] ?? KIND_VAR.silence), alpha),
        drag: false,
        resize: s.op === "remove" && !s.locked,
      });
    });
  }, [segments, peaks, media, theme]);

  return <div ref={el} className={peaks ? "waveform" : "waveform loading"} />;
}
