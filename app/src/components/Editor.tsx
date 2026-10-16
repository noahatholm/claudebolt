import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { mediaUrl } from "../engine";
import { KIND_LABEL, kindClass } from "../kinds";
import { playbackAction } from "../playback";
import { useStore } from "../store";
import { fmt, outputToSource, sourceToOutput } from "../timeMap";
import { DetectionPanel } from "./DetectionPanel";
import { Icon } from "./Icon";
import { RenderDialog } from "./RenderDialog";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { Notice, Segmented } from "./ui";
import { Waveform } from "./Waveform";

export function Editor({ onSettings }: { onSettings: () => void }) {
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

  // Legend: only the kinds of edit that are actually on the timeline.
  const kinds = useMemo(() => {
    const k = new Set<string>();
    for (const s of segments) if (s.op === "speed") k.add("speed");
    else if (s.op === "remove") k.add(s.reason ?? "silence");
    return [...k];
  }, [segments]);

  if (!project) return null;
  const url = mediaUrl(project.id, src.id);
  const outT = sourceToOutput(segments, playhead);
  const fileName = src.path.split(/[\\/]/).pop();

  return (
    <>
      <TopBar onSettings={onSettings} file={src.path}>
        <button className="btn icon ghost" onClick={() => void undo()} title="Undo (Ctrl+Z)" aria-label="Undo">
          <Icon name="undo" />
        </button>
        <button className="btn icon ghost" onClick={() => void redo()} title="Redo (Ctrl+Shift+Z)" aria-label="Redo">
          <Icon name="redo" />
        </button>
        <button className="btn primary" onClick={() => setShowRender(true)} title="Render or export (Ctrl+E)">
          <Icon name="export" />
          Export
        </button>
      </TopBar>

      <div className="workspace">
        <aside className="pane inspector">
          <DetectionPanel />
        </aside>

        <main className="pane stage">
          <div className={isVideo ? "viewer" : "viewer audio"}>
            {isVideo ? (
              <video ref={setMedia} src={url} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
            ) : (
              <audio ref={setMedia} src={url} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
            )}
            {!isVideo && (
              <div className="audio-card">
                <div className={playing ? "eq on" : "eq"} aria-hidden>
                  {[0, 1, 2, 3, 4].map((i) => <i key={i} />)}
                </div>
                <b>{fileName}</b>
                <span>Audio · {fmt(project.duration)}</span>
              </div>
            )}
            {view === "edited" && (
              <span className="viewer-badge">
                <Icon name="scissors" size={12} /> Edited preview
              </span>
            )}
          </div>

          {project.warnings.map((w) => <Notice key={w}>{w}</Notice>)}

          <div className="transport">
            <button
              className="btn icon ghost"
              onClick={() => media && (media.currentTime = outputToSource(segments, 0))}
              title="Go to start"
              aria-label="Go to start"
            >
              <Icon name="skipBack" />
            </button>
            <button className="play" onClick={toggle} title="Play / pause (Space)" aria-label={playing ? "Pause" : "Play"}>
              <Icon name={playing ? "pause" : "play"} size={18} />
            </button>
            <div className="tc-group">
              <span className="eyebrow">Source</span>
              <span className="tc">{fmt(playhead)}<small>/ {fmt(project.duration)}</small></span>
            </div>
            <div className="tc-group">
              <span className="eyebrow">Edited</span>
              <span className="tc accent">{fmt(outT)}<small>/ {fmt(summary?.output_duration ?? 0)}</small></span>
            </div>
            <span className="spacer" />
            <Segmented
              value={view}
              onChange={setView}
              options={[
                { value: "source", label: "Source", hint: "Play the original recording" },
                { value: "edited", label: "Edited", hint: "Play with cuts skipped and speed-ups applied" },
              ]}
            />
          </div>
        </main>

        <aside className="pane side">
          <Sidebar seek={(t) => media && (media.currentTime = t)} />
        </aside>

        <section className="pane dock">
          <div className="dock-head">
            <span className="pane-title">Timeline</span>
            <div className="legend">
              {kinds.length ? (
                kinds.map((k) => (
                  <span key={k} className={kindClass(k)}><i />{KIND_LABEL[k] ?? k}</span>
                ))
              ) : (
                <span className="muted">Run detection to mark silences. Click a marked region to restore it, drag its edges to adjust.</span>
              )}
            </div>
            <span className="spacer" />
            {summary && (
              <>
                <span className="sum">
                  <b>{fmt(summary.output_duration)}</b> from {fmt(summary.source_duration)}
                </span>
                <span className="pill" title={`${summary.removed_seconds.toFixed(1)} s removed`}>
                  −{summary.percent_removed}%
                </span>
              </>
            )}
          </div>
          <Waveform media={media} duration={project.duration} />
        </section>
      </div>

      {showRender && <RenderDialog onClose={() => setShowRender(false)} />}
    </>
  );
}
