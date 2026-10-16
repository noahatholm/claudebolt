import { useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.esm.js";
import TimelinePlugin from "wavesurfer.js/dist/plugins/timeline.esm.js";
import { KIND_VAR } from "../kinds";
import { useStore } from "../store";
import { useTheme } from "../theme";

interface Props {
  media: HTMLMediaElement | null;
  duration: number;
  /** Magnification over fit-to-width (1 = whole file visible). */
  zoom: number;
  onZoom: (zoom: number) => void;
  /** Reports the largest useful zoom for this file and width. */
  onMaxZoom: (max: number) => void;
}

/** Deepest zoom, in pixels per second of source. */
const MAX_PX_PER_SEC = 500;

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function tint(hex: string, a: number) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

const waveColors = () => ({ waveColor: token("--wave"), progressColor: token("--wave-progress"), cursorColor: token("--cursor") });

/** Waveform from engine-supplied peaks (instant on long files), with editable removed/speed regions. */
export function Waveform({ media, duration, zoom, onZoom, onMaxZoom }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const regions = useRef<RegionsPlugin | null>(null);
  const known = useRef(new Map<string, { a: number; b: number }>());
  const peaks = useStore((s) => s.peaks);
  const segments = useStore((s) => s.segments);
  const edit = useStore((s) => s.edit);
  const theme = useTheme((s) => s.resolved);
  const applied = useRef(0); // px/sec last handed to wavesurfer (0 = fit)
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const fitPps = () => (el.current?.clientWidth ?? 1000) / Math.max(duration, 0.001);
  const maxZoom = () => Math.max(1, MAX_PX_PER_SEC / fitPps());

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
      plugins: [
        rp,
        TimelinePlugin.create({ height: 16, style: { fontSize: "10px", color: "inherit" }, secondaryLabelOpacity: 0.6 }),
      ],
    });
    applied.current = 0;
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
    // Ctrl/Cmd + wheel zooms around the pointer; plain wheel keeps scrolling the page as before.
    const box = el.current;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const z = Math.min(maxZoom(), Math.max(1, zoomRef.current * Math.exp(-e.deltaY * 0.0025)));
      const x = e.clientX - box.getBoundingClientRect().left;
      const oldPps = applied.current || fitPps();
      const t = (w.getScroll() + x) / oldPps;
      const pps = z <= 1 ? 0 : fitPps() * z;
      applied.current = pps;
      w.zoom(pps);
      if (pps) w.setScroll(t * pps - x);
      onZoom(z);
    };
    box.addEventListener("wheel", onWheel, { passive: false });
    const ro = new ResizeObserver(() => onMaxZoom(maxZoom()));
    ro.observe(box);
    return () => {
      box.removeEventListener("wheel", onWheel);
      ro.disconnect();
      w.destroy();
      ws.current = null;
      regions.current = null;
    };
  }, [peaks, media, duration, edit]); // eslint-disable-line react-hooks/exhaustive-deps

  // Button / keyboard zoom: keep the playhead in view.
  useEffect(() => {
    const w = ws.current;
    if (!w || !el.current) return;
    const pps = zoom <= 1 ? 0 : fitPps() * Math.min(zoom, maxZoom());
    if (Math.abs(pps - applied.current) < 1e-6) return;
    applied.current = pps;
    w.zoom(pps);
    if (pps) w.setScroll(w.getCurrentTime() * pps - el.current.clientWidth / 2);
  }, [zoom, peaks, media]); // eslint-disable-line react-hooks/exhaustive-deps

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
