import { useCallback, useEffect, useRef, useState } from "react";
import { mediaUrl } from "../engine";
import { playbackAction } from "../playback";
import { useStore } from "../store";
import { fmt, outputToSource, sourceToOutput } from "../timeMap";
import { ActivityFeed } from "./ActivityFeed";
import { DetectionPanel } from "./DetectionPanel";
import { RenderDialog } from "./RenderDialog";
import { TranscriptPanel } from "./TranscriptPanel";
import { Waveform } from "./Waveform";

export function Editor() {
  const { project, segments, summary, view, setView, undo, redo, edit, setPlayhead, playhead } = useStore();
  const [media, setMedia] = useState<HTMLMediaElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [showRender, setShowRender] = useState(false);
  const raf = useRef(0);
  const viewRef = useRef(view);
  viewRef.current = view;
  const segsRef = useRef(segments);
  segsRef.current = segments;

  const src = project!.sources[0];
  const isVideo = src.kind === "video";

  // The media element is the clock. In "edited" view we skip removed spans and ride speed spans.
  const tick = useCallback(() => {
    const m = media;
    if (m) {
      setPlayhead(m.currentTime);
      if (viewRef.current === "edited" && !m.paused) {
        const a = playbackAction(segsRef.current, m.currentTime);
        if (a.seekTo !== undefined) m.currentTime = a.seekTo;
        if (m.playbackRate !== a.rate) m.playbackRate = a.rate;
        m.muted = a.muted;
      }
    }
    raf.current = requestAnimationFrame(tick);
  }, [media, setPlayhead]);

  useEffect(() => {
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [tick]);

  useEffect(() => {
    if (media && view === "source") {
      media.playbackRate = 1;
      media.muted = false;
    }
  }, [view, media]);

  const toggle = useCallback(() => {
    if (!media) return;
    if (media.paused) void media.play();
    else media.pause();
  }, [media]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA") return;
      const step = isVideo ? 1 / 30 : 0.01;
      if (e.code === "Space") { e.preventDefault(); toggle(); }
      else if (e.key === "z" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void (e.shiftKey ? redo() : undo()); }
      else if (e.key === "e" && e.ctrlKey) { e.preventDefault(); setShowRender(true); }
      else if (e.key === "r" && e.ctrlKey) { e.preventDefault(); setShowRender(true); }
      else if (e.key === "ArrowLeft" && media) {
        if (e.shiftKey) {
          const prev = [...segsRef.current].reverse().find((s) => s.src_end < media.currentTime - 0.05);
          if (prev) media.currentTime = prev.src_end;
        } else media.currentTime -= step;
      } else if (e.key === "ArrowRight" && media) {
        if (e.shiftKey) {
          const next = segsRef.current.find((s) => s.src_start > media.currentTime + 0.05);
          if (next) media.currentTime = next.src_start;
        } else media.currentTime += step;
      } else if (e.key === "l" && media) { media.playbackRate = 2; void media.play(); }
      else if (e.key === "k") media?.pause();
      else if (e.key === "j" && media) media.currentTime -= 2;
      else if (e.key === "x" && media) {
        const s = segsRef.current.find((x) => media.currentTime >= x.src_start && media.currentTime < x.src_end);
        if (s) void edit([{ action: s.op === "keep" ? "remove" : "keep", start: s.src_start, end: s.src_end }]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [media, toggle, undo, redo, edit, isVideo]);

  if (!project) return null;
  const url = mediaUrl(project.id, src.id);
  const outT = sourceToOutput(segments, playhead);

  return (
    <div className="editor">
      <aside className="left">
        <DetectionPanel />
      </aside>
      <main className="center-col">
        <div className="player">
          {isVideo ? (
            <video ref={setMedia} src={url} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
          ) : (
            <audio ref={setMedia} src={url} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
          )}
          {!isVideo && <div className="audio-title">{src.path.split(/[\\/]/).pop()}</div>}
        </div>
        <div className="transport">
          <button onClick={toggle}>{playing ? "Pause" : "Play"}</button>
          <span className="mono">{fmt(playhead)} / {fmt(project.duration)}</span>
          <span className="mono muted">edited {fmt(outT)} / {fmt(summary?.output_duration ?? 0)}</span>
          <span className="spacer" />
          <div className="seg">
            <button className={view === "source" ? "on" : ""} onClick={() => setView("source")}>Source</button>
            <button className={view === "edited" ? "on" : ""} onClick={() => setView("edited")}>Edited</button>
          </div>
          <button onClick={() => void undo()}>Undo</button>
          <button onClick={() => void redo()}>Redo</button>
          <button className="primary" onClick={() => setShowRender(true)}>Render / Export</button>
        </div>
        {project.warnings.map((w) => <div key={w} className="warn">{w}</div>)}
        <Waveform media={media} duration={project.duration} />
        <div className="summary">
          {summary && (
            <>
              <b>{fmt(summary.output_duration)}</b> from {fmt(summary.source_duration)} &nbsp;
              <span className="muted">(-{fmt(summary.removed_seconds)}, {summary.percent_removed}% removed)</span>
            </>
          )}
          <button className="link" onClick={() => media && (media.currentTime = outputToSource(segments, 0))}>go to start</button>
        </div>
        <ActivityFeed />
      </main>
      <aside className="right">
        <TranscriptPanel seek={(t) => media && (media.currentTime = t)} />
      </aside>
      {showRender && <RenderDialog onClose={() => setShowRender(false)} />}
    </div>
  );
}
