import { useEffect, useMemo } from "react";
import { useStore } from "../store";
import { fmt } from "../timeMap";
import type { Proposal } from "../types";

const KIND_CLASS: Record<string, string> = { filler: "k-filler", false_start: "k-false", retake: "k-retake" };

export function TranscriptPanel({ seek }: { seek: (t: number) => void }) {
  const { project, words, proposals, selection, setSelection, edit, transcribe, cleanup, decide, jobs, playhead } = useStore();

  const byWord = useMemo(() => {
    const m = new Map<number, Proposal>();
    for (const p of proposals) {
      if (p.status !== "pending" || !p.word_range) continue;
      for (let i = p.word_range[0]; i <= p.word_range[1]; i++) m.set(i, p);
    }
    return m;
  }, [proposals]);

  const running = Object.values(jobs).find((j) => j.kind === "transcribe" && j.status === "running");

  const cut = () => {
    if (!selection) return;
    void edit([{ action: "remove", word_range: selection }]);
    setSelection(null);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT") return;
      if ((e.key === "d" || e.key === "Delete") && selection) cut();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  if (!project) return null;

  const click = (i: number, e: React.MouseEvent) => {
    if (e.shiftKey && selection) setSelection([Math.min(selection[0], i), Math.max(selection[1], i)]);
    else setSelection([i, i]);
    seek(words[i].start);
  };

  const pending = proposals.filter((p) => p.status === "pending");

  return (
    <div className="panel transcript">
      <h3>Transcript</h3>
      <div className="row">
        <button onClick={() => void transcribe()} disabled={!!running}>
          {running ? `Transcribing ${Math.round(running.progress * 100)}%` : words.length ? "Re-transcribe" : "Transcribe (local Whisper)"}
        </button>
        <button onClick={() => void cleanup()} disabled={!words.length}>Find fillers & retakes</button>
      </div>
      {!words.length && <p className="muted small">The first run downloads a speech model (small.en, about 480 MB). It never leaves your computer.</p>}
      <div className="words">
        {words.map((w) => {
          const p = byWord.get(w.i);
          const sel = selection && w.i >= selection[0] && w.i <= selection[1];
          const now = playhead >= w.start && playhead < w.end;
          return (
            <span
              key={w.i}
              className={["w", w.removed ? "gone" : "", p ? KIND_CLASS[p.kind] : "", sel ? "sel" : "", now ? "now" : ""].join(" ")}
              onClick={(e) => click(w.i, e)}
              title={p ? `${p.kind} ${Math.round(p.confidence * 100)}%` : fmt(w.start)}
            >
              {w.text}{" "}
            </span>
          );
        })}
      </div>
      {selection && <button onClick={cut}>Cut selected words (D)</button>}
      {pending.length > 0 && (
        <div className="proposals">
          <div className="row">
            <b>{pending.length} suggestions</b>
            <button onClick={() => void decide("accept", { min_confidence: 0.8 })}>Accept all &ge; 80%</button>
            <button onClick={() => void decide("reject", {})}>Reject all</button>
          </div>
          {pending.slice(0, 200).map((p) => (
            <div key={p.id} className={`prop ${KIND_CLASS[p.kind]}`}>
              <span onClick={() => seek(p.start)} className="ptext">
                <small>{p.kind.replace("_", " ")} {Math.round(p.confidence * 100)}%</small> {p.text}
              </span>
              <button onClick={() => void decide("accept", { ids: [p.id] })}>Cut</button>
              <button onClick={() => void decide("reject", { ids: [p.id] })}>Keep</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
