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
  const [zoom, setZoom] = useState(1);
  const [maxZoom, setMaxZoom] = useState(64);
  const zoomSpan = Math.log(Math.max(maxZoom, 1.01)); // slider is logarithmic: 0 = fit, 1 = deepest
  const zoomBy = useCallback((f: number) => setZoom((z) => Math.min(maxZoom, Math.max(1, z * f))), [maxZoom]);
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
      } else if ((e.key === "=" || e.key === "+") && !e.ctrlKey) zoomBy(1.6);
      else if (e.key === "-" && !e.ctrlKey) zoomBy(1 / 1.6);
      else if (e.key === "0" && !e.ctrlKey) setZoom(1);
      else if (e.key === "l" && media) { media.playbackRate = 2; void media.play(); }
      else if (e.key === "k") media?.pause();
      else if (e.key === "j" && media) media.currentTime -= 2;
      else if (e.key === "x" && media) {
        const s = segsRef.current.find((x) => media.currentTime >= x.src_start && media.currentTime < x.src_end);
        if (s) void edit([{ action: s.op === "keep" ? "remove" : "keep", start: s.src_start, end: s.src_end }]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [media, toggle, undo, redo, edit, isVideo, zoomBy]);

  // Legend: only the kinds of edit that are actually on the timeline.
  const kinds = useMemo(() => {
    const k = new Set<string>();
    for (const s of segments) if (s.op === "speed") k.add("speed");
    else if (s.op === "remove") k.add(s.reason ?? "silence");
    return [...k];
  }, [segments]);

  if (!project) return null;
  const url = mediaUrl(project.id, src.id);
  // Backstop for the frame loop above, which browsers pause in hidden or throttled windows.
  const clockEvents = {
    onTimeUpdate: (e: React.SyntheticEvent<HTMLMediaElement>) => setPlayhead(e.currentTarget.currentTime),
    onSeeked: (e: React.SyntheticEvent<HTMLMediaElement>) => setPlayhead(e.currentTarget.currentTime),
  };
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
              <video ref={setMedia} src={url} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} {...clockEvents} />
            ) : (
              <audio ref={setMedia} src={url} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} {...clockEvents} />
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
                <span className="muted" title="Click a marked region to restore it, drag its edges to adjust. Ctrl + scroll to zoom.">Run detection to mark silences.</span>
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
            <div className="zoom" role="group" aria-label="Timeline zoom">
              <button className="btn icon sm ghost" onClick={() => zoomBy(1 / 1.6)} disabled={zoom <= 1} title="Zoom out (−)" aria-label="Zoom out">
                <Icon name="zoomOut" size={14} />
              </button>
              <input
                className="range"
                type="range"
                min={0}
                max={1}
                step={0.001}
                value={Math.log(zoom) / zoomSpan}
                style={{ ["--p" as string]: `${(Math.log(zoom) / zoomSpan) * 100}%` }}
                onChange={(e) => setZoom(Math.exp(parseFloat(e.target.value) * zoomSpan))}
                aria-label="Zoom level"
                title="Zoom (Ctrl + scroll on the waveform)"
              />
              <button className="btn icon sm ghost" onClick={() => zoomBy(1.6)} disabled={zoom >= maxZoom} title="Zoom in (+)" aria-label="Zoom in">
                <Icon name="zoomIn" size={14} />
              </button>
              <button className="btn icon sm ghost" onClick={() => setZoom(1)} disabled={zoom <= 1} title="Fit whole file (0)" aria-label="Fit whole file">
                <Icon name="fit" size={14} />
              </button>
            </div>
          </div>
          <Waveform media={media} duration={project.duration} zoom={zoom} onZoom={setZoom} onMaxZoom={setMaxZoom} />
        </section>
      </div>

      {showRender && <RenderDialog onClose={() => setShowRender(false)} />}
    </>
  );
}
