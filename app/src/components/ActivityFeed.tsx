import { useStore } from "../store";

/** Edits made by the user or an AI agent (over MCP), each with an undo. */
export function ActivityFeed() {
  const { activity, undo } = useStore();
  if (!activity.length) return <div className="feed muted small">Edits from you or an AI agent appear here.</div>;
  return (
    <div className="feed">
      {activity.map((a, i) => (
        <div key={a.id} className={`feed-item ${a.actor}`}>
          <span className="badge">{a.actor}</span>
          <span className="ftext">{a.ops.join("; ")}</span>
          {i === 0 && <button onClick={() => void undo()}>Undo</button>}
        </div>
      ))}
    </div>
  );
}
