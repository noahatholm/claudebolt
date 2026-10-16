import { useStore } from "../store";
import { Icon } from "./Icon";

const WHO: Record<string, string> = { user: "You", agent: "AI agent" };

/** Edits made by the user or an AI agent (over MCP), each with an undo. */
export function ActivityFeed() {
  const { activity, undo } = useStore();
  if (!activity.length) {
    return (
      <div className="empty">
        <span className="empty-icon"><Icon name="history" size={20} /></span>
        <h4>No edits yet</h4>
        <p>Edits you make, or that an AI agent makes over MCP, show up here as they happen.</p>
      </div>
    );
  }
  return (
    <div className="scroll">
      <div className="feed">
        {activity.map((a, i) => (
          <div key={a.id} className={`feed-item ${a.actor}`}>
            <span className="avatar"><Icon name={a.actor === "agent" ? "sparkle" : "user"} size={13} /></span>
            <div className="grow">
              <div className="feed-who">
                {WHO[a.actor] ?? a.actor}
                <time>{new Date(a.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
              </div>
              <div className="feed-ops">{a.ops.join("; ") || "edit"}</div>
            </div>
            {i === 0 && (
              <button className="btn sm" onClick={() => void undo()}>
                <Icon name="undo" size={13} />
                Undo
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
