import { useEffect, useMemo, useState } from "react";
import { kindClass } from "../kinds";
import { useStore } from "../store";
import { fmt } from "../timeMap";
import type { Proposal } from "../types";
import { Icon } from "./Icon";
import { Progress } from "./ui";

export function TranscriptPanel({ seek, onFound }: { seek: (t: number) => void; onFound: () => void }) {
  const { project, words, proposals, selection, setSelection, edit, transcribe, cleanup, jobs, playhead } = useStore();
  const [finding, setFinding] = useState(false);

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

  const find = async () => {
    setFinding(true);
    await cleanup();
    setFinding(false);
    onFound();
  };

  if (!words.length) {
    return (
      <div className="empty">
        <span className="empty-icon"><Icon name="text" size={20} /></span>
        <h4>No transcript yet</h4>
        <p>
          Transcribe with local Whisper to edit by text and find filler words and retakes. The first run downloads a
          speech model (small.en, about 480 MB). It never leaves your computer.
        </p>
        {running ? (
          <div className="stack w100">
            <Progress value={running.progress} />
            <span className="small muted">Transcribing {Math.round(running.progress * 100)}%</span>
          </div>
        ) : (
          <button className="btn primary" onClick={() => void transcribe()}>
            <Icon name="waveform" />
            Transcribe
          </button>
        )}
      </div>
    );
  }

  const n = selection ? selection[1] - selection[0] + 1 : 0;

  return (
    <>
      <div className="toolbar">
        <button className="btn sm ghost" onClick={() => void transcribe()} disabled={!!running}>
          <Icon name="refresh" size={13} />
          {running ? `Transcribing ${Math.round(running.progress * 100)}%` : "Re-transcribe"}
        </button>
        <span className="spacer" />
        <button className="btn sm" onClick={find} disabled={finding}>
          {finding ? <span className="spinner" /> : <Icon name="sparkle" size={13} />}
          Find fillers &amp; retakes
        </button>
      </div>
      {running && <Progress value={running.progress} />}
      <div className="scroll">
        <div className="words">
          {words.map((w) => {
            const p = byWord.get(w.i);
            const sel = selection && w.i >= selection[0] && w.i <= selection[1];
            const now = playhead >= w.start && playhead < w.end;
            return (
              <span
                key={w.i}
                className={["w", w.removed ? "gone" : "", p ? `k ${kindClass(p.kind)}` : "", sel ? "sel" : "", now ? "now" : ""].join(" ")}
                onClick={(e) => click(w.i, e)}
                title={p ? `${p.kind.replace("_", " ")} ${Math.round(p.confidence * 100)}%` : fmt(w.start)}
              >
                {w.text}{" "}
              </span>
            );
          })}
        </div>
      </div>
      {selection && (
        <div className="selbar">
          <span className="grow">
            <b>{n}</b> {n === 1 ? "word" : "words"} selected <span className="muted small">· shift-click to extend</span>
          </span>
          <button className="btn sm ghost" onClick={() => setSelection(null)}>Clear</button>
          <button className="btn sm primary" onClick={cut}>
            <Icon name="scissors" size={13} />
            Cut <span className="kbd">D</span>
          </button>
        </div>
      )}
    </>
  );
}
