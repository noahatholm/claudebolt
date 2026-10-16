import { useEffect, useMemo, useRef, useState } from "react";
import { kindClass } from "../kinds";
import { useStore } from "../store";
import { fmt } from "../timeMap";
import type { Proposal, Word } from "../types";
import { Icon } from "./Icon";
import { Progress } from "./ui";

/** Index of the word under (or most recently before) time t, or -1. Words are sorted by start. */
function wordAt(words: Word[], t: number): number {
  let lo = 0;
  let hi = words.length - 1;
  let best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid].start <= t) {
      best = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return best;
}

export function TranscriptPanel({ seek, onFound }: { seek: (t: number) => void; onFound: () => void }) {
  const { project, words, proposals, selection, setSelection, edit, transcribe, cleanup, jobs } = useStore();
  // Subscribing to the index (not the playhead) re-renders only when playback reaches another word.
  const nowIdx = useStore((s) => wordAt(s.words, s.playhead));
  const nowLive = useStore((s) => nowIdx >= 0 && s.playhead < (s.words[nowIdx]?.end ?? 0));
  const [finding, setFinding] = useState(false);
  const [follow, setFollow] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);

  // Keep the current word in the middle band of the pane while following.
  useEffect(() => {
    const box = scroller.current;
    if (!follow || !box || nowIdx < 0) return;
    const el = box.querySelector<HTMLElement>(`[data-i="${nowIdx}"]`);
    if (!el) return;
    const b = box.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (r.top < b.top + b.height * 0.2 || r.bottom > b.bottom - b.height * 0.35) {
      box.scrollTo({ top: box.scrollTop + r.top - b.top - b.height * 0.35, behavior: "smooth" });
    }
  }, [nowIdx, follow]);

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
        <button
          className={follow ? "btn sm toggle on" : "btn sm toggle"}
          onClick={() => setFollow(!follow)}
          aria-pressed={follow}
          title="Scroll the transcript along with playback"
        >
          <Icon name="target" size={13} />
          Follow
        </button>
        <button className="btn sm" onClick={find} disabled={finding}>
          {finding ? <span className="spinner" /> : <Icon name="sparkle" size={13} />}
          Find fillers &amp; retakes
        </button>
      </div>
      {running && <Progress value={running.progress} />}
      <div className="scroll" ref={scroller} onWheel={() => follow && setFollow(false)}>
        <div className="words">
          {words.map((w, i) => {
            const p = byWord.get(w.i);
            const sel = selection && w.i >= selection[0] && w.i <= selection[1];
            const now = i === nowIdx;
            return (
              <span
                key={w.i}
                data-i={i}
                className={["w", w.removed ? "gone" : "", p ? `k ${kindClass(p.kind)}` : "", sel ? "sel" : "", now ? (nowLive ? "now" : "now gap") : "", i < nowIdx ? "past" : ""].join(" ")}
                onClick={(e) => click(w.i, e)}
                title={p ? `${p.kind.replace("_", " ")} ${Math.round(p.confidence * 100)}%` : fmt(w.start)}
              >
                {w.text}{" "}
              </span>
            );
          })}
        </div>
      </div>
      {!follow && nowIdx >= 0 && !selection && (
        <button className="jump" onClick={() => setFollow(true)}>
          <Icon name="target" size={13} />
          Back to playhead
        </button>
      )}
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
