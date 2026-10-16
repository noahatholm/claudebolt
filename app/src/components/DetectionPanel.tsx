import { useEffect, useState } from "react";
import { get } from "../engine";
import { useStore } from "../store";
import type { Detection } from "../types";
import { Icon } from "./Icon";
import { Notice, NumField, Segmented } from "./ui";

interface Analysis {
  suggested_threshold: number;
  histogram: { edges: number[]; counts: number[] };
  warnings: string[];
}

const DEFAULTS: Detection = {
  mode: "rms", threshold: -35, grace: 0.5, pad_left: 0.01, pad_right: 0.15,
  min_keep: 0.75, silence_action: "cut", speed_rate: 3,
};

// Slider range, and the dB span the histogram covers.
const MIN_DB = -80;
const MAX_DB = -10;
const HIST_FLOOR = -90;

const MODE_HINT: Record<Detection["mode"], string> = {
  rms: "Fast and predictable. Best for a clean mic with a quiet room.",
  vad: "Listens for a voice, so steady noise, hum or music beds count as silence.",
  both: "Strictest: cuts anything quiet and anything without a voice.",
};

export function DetectionPanel() {
  const { project, settings, detect, summary } = useStore();
  const [d, setD] = useState<Detection>(DEFAULTS);
  const [an, setAn] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  // How much the last Detect changed the edited length (null before the first run).
  const [change, setChange] = useState<number | null>(null);

  useEffect(() => {
    if (settings?.detection) setD({ ...DEFAULTS, ...settings.detection });
  }, [settings]);

  useEffect(() => {
    if (!project) return;
    get<Analysis>(`/projects/${project.id}/analyze`).then(setAn).catch(() => setAn(null));
  }, [project?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const num = (k: keyof Detection) => (v: number) => setD({ ...d, [k]: v });
  const thr = d.threshold === "auto" ? an?.suggested_threshold ?? -35 : d.threshold;
  const counts = an?.histogram.counts ?? [];
  const edges = an?.histogram.edges;
  const max = Math.max(1, ...counts);
  const thrPct = ((thr - HIST_FLOOR) / -HIST_FLOOR) * 100;
  const binBelow = (i: number) =>
    edges && edges.length > i + 1 ? (edges[i] + edges[i + 1]) / 2 < thr : (i + 0.5) / counts.length < thrPct / 100;

  const run = async () => {
    setBusy(true);
    const before = useStore.getState().summary?.output_duration;
    await detect(d);
    const after = useStore.getState().summary?.output_duration;
    setChange(before === undefined || after === undefined ? null : after - before);
    setBusy(false);
  };

  return (
    <>
      <div className="pane-head">
        <Icon name="waveform" />
        <span className="pane-title">Silence detection</span>
      </div>

      <div className="inspector-body">
        <section className="section">
          <span className="eyebrow">Detect by</span>
          <Segmented
            full
            value={d.mode}
            onChange={(mode) => setD({ ...d, mode })}
            options={[
              { value: "rms", label: "Volume", hint: "Cut stretches quieter than the threshold" },
              { value: "vad", label: "Speech", hint: "Cut stretches with no voice in them, however loud (voice activity detection)" },
              { value: "both", label: "Both", hint: "Cut when it is quiet or when nobody is speaking" },
            ]}
          />
          <p className="hint">{MODE_HINT[d.mode]}</p>
        </section>

        <section className={d.mode === "vad" ? "section off" : "section"} aria-disabled={d.mode === "vad"}>
          <div className="section-head">
            <span className="eyebrow">Threshold</span>
            <span className="readout">{typeof thr === "number" ? thr.toFixed(0) : thr} dB</span>
          </div>
          <div className="hist" title="Loudness histogram. Everything left of the line counts as silence.">
            <span className="hist-zone" style={{ width: `${thrPct}%` }} />
            {counts.map((c, i) => (
              <i key={i} className={binBelow(i) ? "below" : ""} style={{ height: `${(c / max) * 100}%` }} />
            ))}
            {an && <b className="thr" style={{ left: `${thrPct}%` }} />}
          </div>
          <div className="hist-axis"><span>{HIST_FLOOR} dB</span><span>0</span></div>
          <input
            className="range"
            type="range"
            min={MIN_DB}
            max={MAX_DB}
            step={1}
            value={thr}
            style={{ ["--p" as string]: `${((thr - MIN_DB) / (MAX_DB - MIN_DB)) * 100}%` }}
            onChange={(e) => setD({ ...d, threshold: parseFloat(e.target.value) })}
            aria-label="Threshold"
          />
          <button
            className="btn sm"
            disabled={!an}
            onClick={() => an && setD({ ...d, threshold: Math.round(an.suggested_threshold) })}
            title="Use the threshold suggested from this file's loudness"
          >
            <Icon name="sparkle" size={13} />
            Suggested {an ? `${an.suggested_threshold.toFixed(0)} dB` : "…"}
          </button>
          {an?.warnings.map((w) => <Notice key={w}>{w}</Notice>)}
          {d.mode === "vad" && <p className="hint">Speech mode ignores the loudness threshold.</p>}
        </section>

        <section className="section">
          <span className="eyebrow">Timing</span>
          <div className="grid2">
            <NumField label="Grace" suffix="s" step={0.1} min={0} value={d.grace} onChange={num("grace")} hint="Pauses this short or shorter are kept" />
            <NumField label="Min keep" suffix="s" step={0.05} min={0} value={d.min_keep} onChange={num("min_keep")} hint="Sounds shorter than this are cut along with the silence" />
            <NumField label="Pad before" suffix="s" step={0.01} min={0} value={d.pad_left} onChange={num("pad_left")} hint="Audio kept before speech starts" />
            <NumField label="Pad after" suffix="s" step={0.01} min={0} value={d.pad_right} onChange={num("pad_right")} hint="Audio kept after speech ends" />
          </div>
        </section>

        <section className="section">
          <span className="eyebrow">Silences</span>
          <Segmented
            full
            value={d.silence_action}
            onChange={(silence_action) => setD({ ...d, silence_action })}
            options={[
              { value: "cut", label: "Cut", icon: "scissors" },
              { value: "speed", label: "Speed up", icon: "bolt" },
            ]}
          />
          {d.silence_action === "speed" && (
            <NumField label="Speed rate" suffix="×" step={0.5} min={1.1} value={d.speed_rate} onChange={num("speed_rate")} />
          )}
        </section>
      </div>

      <div className="inspector-foot">
        {!!summary?.removed_seconds && (
          <div className="result">
            <b>−{summary.percent_removed}%</b>
            <span>{summary.removed_seconds.toFixed(1)} s removed</span>
          </div>
        )}
        {change !== null && !busy && (
          <p className="hint">
            {Math.abs(change) < 0.05
              ? "Same cuts as the last run."
              : `${Math.abs(change).toFixed(1)} s ${change < 0 ? "more" : "less"} cut than the last run.`}
          </p>
        )}
        <button className="btn primary lg block" disabled={busy} onClick={run}>
          {busy ? <span className="spinner" /> : <Icon name="bolt" />}
          {busy ? "Detecting…" : "Detect silences"}
        </button>
      </div>
    </>
  );
}
