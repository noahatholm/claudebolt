import { useEffect, useState } from "react";
import { useStore } from "../store";
import { ActivityFeed } from "./ActivityFeed";
import { Icon, type IconName } from "./Icon";
import { SuggestionsPanel } from "./SuggestionsPanel";
import { TranscriptPanel } from "./TranscriptPanel";

type Tab = "transcript" | "suggestions" | "activity";

export function Sidebar({ seek }: { seek: (t: number) => void }) {
  const [tab, setTab] = useState<Tab>("transcript");
  const pending = useStore((s) => s.proposals.filter((p) => p.status === "pending").length);
  const activity = useStore((s) => s.activity);
  const [seen, setSeen] = useState(0);
  const latest = activity[0]?.id ?? 0;

  useEffect(() => {
    if (tab === "activity") setSeen(latest);
  }, [tab, latest]);

  const tabs: { id: Tab; label: string; icon: IconName; count?: number; dot?: boolean }[] = [
    { id: "transcript", label: "Transcript", icon: "text" },
    { id: "suggestions", label: "Suggestions", icon: "sparkle", count: pending },
    { id: "activity", label: "Activity", icon: "history", dot: latest > seen && tab !== "activity" },
  ];

  return (
    <>
      <nav className="tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "tab on" : "tab"} onClick={() => setTab(t.id)}>
            <Icon name={t.icon} size={14} />
            {t.label}
            {!!t.count && <span className="count">{t.count}</span>}
            {t.dot && <span className="live" title="New edits" />}
          </button>
        ))}
      </nav>
      <div className="tab-body">
        {tab === "transcript" && <TranscriptPanel seek={seek} onFound={() => setTab("suggestions")} />}
        {tab === "suggestions" && <SuggestionsPanel seek={seek} />}
        {tab === "activity" && <ActivityFeed />}
      </div>
    </>
  );
}
