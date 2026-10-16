import { KIND_LABEL, kindClass } from "../kinds";
import { useStore } from "../store";
import { fmt } from "../timeMap";
import { Icon } from "./Icon";

/** Pending filler / false-start / retake proposals: each is cut only once accepted. */
export function SuggestionsPanel({ seek }: { seek: (t: number) => void }) {
  const { words, proposals, decide, cleanup } = useStore();
  const pending = proposals.filter((p) => p.status === "pending");

  if (!pending.length) {
    return (
      <div className="empty">
        <span className="empty-icon"><Icon name="sparkle" size={20} /></span>
        <h4>No pending suggestions</h4>
        <p>
          {words.length
            ? "Scan the transcript for filler words, false starts and retakes. Nothing is cut until you accept it."
            : "Transcribe first, then scan for filler words, false starts and retakes."}
        </p>
        {words.length > 0 && (
          <button className="btn primary" onClick={() => void cleanup()}>
            <Icon name="sparkle" />
            Find fillers &amp; retakes
          </button>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="toolbar">
        <span className="small muted grow">{pending.length} pending</span>
        <button className="btn sm ghost" onClick={() => void decide("reject", {})}>Keep all</button>
        <button className="btn sm primary" onClick={() => void decide("accept", { min_confidence: 0.8 })}>
          <Icon name="check" size={13} />
          Cut all ≥ 80%
        </button>
      </div>
      <div className="scroll">
        <div className="props">
          {pending.slice(0, 200).map((p) => {
            const pct = Math.round(p.confidence * 100);
            return (
              <div key={p.id} className={`prop ${kindClass(p.kind)}`}>
                <span className="prop-bar" />
                <button className="prop-main" onClick={() => seek(p.start)} title="Jump to this spot">
                  <span className="prop-meta">
                    <span className="kind">{KIND_LABEL[p.kind] ?? p.kind}</span>
                    <span className="conf" title={`${pct}% confidence`}>
                      <i style={{ ["--v" as string]: `${pct}%` }} />
                      {pct}%
                    </span>
                    <span className="mono">{fmt(p.start)}</span>
                  </span>
                  <span className="prop-text">{p.text}</span>
                </button>
                <div className="prop-actions">
                  <button className="btn icon sm ghost" onClick={() => void decide("reject", { ids: [p.id] })} title="Keep" aria-label="Keep">
                    <Icon name="x" size={14} />
                  </button>
                  <button className="btn icon sm" onClick={() => void decide("accept", { ids: [p.id] })} title="Cut" aria-label="Cut">
                    <Icon name="scissors" size={14} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
