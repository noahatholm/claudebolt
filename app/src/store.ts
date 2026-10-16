import { create } from "zustand";
import { ApiError, get, post } from "./engine";
import type {
  ActivityItem, Describe, Detection, EngineEvent, Job, Proposal, Seg, Summary, Word,
} from "./types";

interface State {
  connected: boolean;
  error: string | null;
  project: Describe | null;
  segments: Seg[];
  words: Word[];
  proposals: Proposal[];
  peaks: number[][] | null;
  summary: Summary | null;
  settings: { detection: Detection } | null;
  jobs: Record<string, Job>;
  activity: ActivityItem[];
  selection: [number, number] | null;
  view: "source" | "edited";
  playhead: number;

  setError(e: unknown): void;
  setConnected(v: boolean): void;
  open(paths: string[]): Promise<void>;
  refresh(): Promise<void>;
  detect(settings: Partial<Detection>): Promise<void>;
  edit(ops: object[]): Promise<void>;
  undo(): Promise<void>;
  redo(): Promise<void>;
  transcribe(model?: string): Promise<void>;
  cleanup(kinds?: string[]): Promise<void>;
  decide(action: "accept" | "reject", body: object): Promise<void>;
  onEvent(e: EngineEvent): void;
  setSelection(s: [number, number] | null): void;
  setView(v: "source" | "edited"): void;
  setPlayhead(t: number): void;
}

let activityId = 0;

export const useStore = create<State>((set, getState) => ({
  connected: false,
  error: null,
  project: null,
  segments: [],
  words: [],
  proposals: [],
  peaks: null,
  summary: null,
  settings: null,
  jobs: {},
  activity: [],
  selection: null,
  view: "source",
  playhead: 0,

  setError: (e) =>
    set({
      error:
        e == null ? null
        : e instanceof ApiError ? (e.hint ? `${e.message} (${e.hint})` : e.message)
        : e instanceof Error ? e.message
        : String(e),
    }),
  setConnected: (connected) => set({ connected }),
  setSelection: (selection) => set({ selection }),
  setView: (view) => set({ view }),
  setPlayhead: (playhead) => set({ playhead }),

  async open(paths) {
    try {
      const p = await post<Describe>("/projects", { paths });
      set({ project: p, error: null, words: [], proposals: [], activity: [], peaks: null });
      await getState().refresh();
    } catch (e) {
      getState().setError(e);
    }
  },

  async refresh() {
    const p = getState().project;
    if (!p) return;
    try {
      const [d, tl, pk, settings] = await Promise.all([
        get<Describe>(`/projects/${p.id}`),
        get<{ segments: Seg[] }>(`/projects/${p.id}/timeline?detail=segments`),
        getState().peaks ? Promise.resolve(null) : get<{ peaks: number[][] }>(`/projects/${p.id}/peaks?px=4000`),
        getState().settings ? Promise.resolve(null) : get<{ detection: Detection }>("/settings"),
      ]);
      const sum = await get<Summary>(`/projects/${p.id}/timeline?detail=summary`);
      let words: Word[] = getState().words;
      let proposals: Proposal[] = getState().proposals;
      if (d.has_transcript) {
        const t = await get<{ words: Word[] }>(`/projects/${p.id}/transcript`);
        words = t.words;
        proposals = (await get<{ proposals: Proposal[] }>(`/projects/${p.id}/proposals`)).proposals;
      }
      set({
        project: d, segments: tl.segments, summary: sum, words, proposals,
        peaks: pk ? pk.peaks : getState().peaks,
        settings: settings ?? getState().settings,
      });
    } catch (e) {
      getState().setError(e);
    }
  },

  async detect(settings) {
    const p = getState().project;
    if (!p) return;
    try {
      await post(`/projects/${p.id}/detect`, { settings });
      await getState().refresh();
    } catch (e) {
      getState().setError(e);
    }
  },

  async edit(ops) {
    const p = getState().project;
    if (!p) return;
    try {
      await post(`/projects/${p.id}/edits`, { ops, expected_version: p.version, actor: "user" });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) await getState().refresh();
      else getState().setError(e);
    }
  },

  async undo() {
    const p = getState().project;
    if (p) await post(`/projects/${p.id}/undo`, {}).catch((e) => getState().setError(e));
  },
  async redo() {
    const p = getState().project;
    if (p) await post(`/projects/${p.id}/redo`, {}).catch((e) => getState().setError(e));
  },

  async transcribe(model) {
    const p = getState().project;
    if (!p) return;
    try {
      const models = await get<{ name: string; installed: boolean }[]>("/models");
      const name = model ?? "small.en";
      if (!models.find((m) => m.name === name)?.installed) await post(`/models/${name}/download`);
      await post(`/projects/${p.id}/transcribe`, { model: name });
    } catch (e) {
      getState().setError(e);
    }
  },

  async cleanup(kinds) {
    const p = getState().project;
    if (!p) return;
    try {
      await post(`/projects/${p.id}/cleanup`, { kinds });
      await getState().refresh();
    } catch (e) {
      getState().setError(e);
    }
  },

  async decide(action, body) {
    const p = getState().project;
    if (!p) return;
    try {
      await post(`/projects/${p.id}/proposals/${action}`, body);
    } catch (e) {
      getState().setError(e);
    }
  },

  onEvent(e) {
    const s = getState();
    if (e.type.startsWith("job.") && e.job) {
      const prev = s.jobs[e.job] ?? ({ job_id: e.job, kind: (e as { kind?: string }).kind ?? "", status: "running", progress: 0 } as Job);
      const status = e.type === "job.done" ? "done" : e.type === "job.failed" ? "failed" : "running";
      set({ jobs: { ...s.jobs, [e.job]: { ...prev, status, progress: e.type === "job.done" ? 1 : e.progress ?? prev.progress, result: e.result, error: e.error } } });
      if (e.type === "job.done") void s.refresh();
      return;
    }
    if (!s.project || e.project !== s.project.id) return;
    if (e.type === "timeline.changed") {
      set({ activity: [{ id: ++activityId, actor: e.actor ?? "user", ops: e.op ?? [], version: e.version ?? 0, at: Date.now() }, ...s.activity].slice(0, 50) });
    }
    // any change to the open project: refetch (cheap, and always consistent with the engine)
    void s.refresh();
  },
}));
