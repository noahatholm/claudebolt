// In-app updates: the shell's updater plugin reads latest.json from the newest GitHub release and
// only installs packages signed with the key baked into the app. Nothing installs without a click.
import type { Update } from "@tauri-apps/plugin-updater";
import { create } from "zustand";
import { isTauri } from "./engine";

type Status = "idle" | "checking" | "available" | "none" | "installing" | "error";

interface UpdateState {
  status: Status;
  version: string | null;
  progress: number | null; // 0..1 while downloading, null when the size is unknown
  error: string | null;
  dismissed: boolean;
  check: (manual?: boolean) => Promise<void>;
  install: () => Promise<void>;
  dismiss: () => void;
}

let pending: Update | null = null;

let enabled: Promise<boolean> | null = null;
/** False for dev runs and builds made from a checkout: only published releases update themselves. */
export function updatesEnabled(): Promise<boolean> {
  if (!isTauri()) return Promise.resolve(false);
  enabled ??= import("@tauri-apps/api/core")
    .then(({ invoke }) => invoke<boolean>("updates_enabled"))
    .catch(() => false);
  return enabled;
}

export const useUpdate = create<UpdateState>((set, get) => ({
  status: "idle",
  version: null,
  progress: null,
  error: null,
  dismissed: false,

  async check(manual = false) {
    if (!(await updatesEnabled()) || ["checking", "installing"].includes(get().status)) return;
    set({ status: "checking", error: null });
    try {
      const { check } = await import("@tauri-apps/plugin-updater");
      const u = await check();
      pending = u;
      set(u ? { status: "available", version: u.version, dismissed: manual ? false : get().dismissed }
            : { status: "none", version: null });
    } catch (e) {
      // offline, GitHub down, or a build with no matching package (the portable zip): stay quiet
      // unless the user asked
      console.warn("update check failed", e);
      set({ status: manual ? "error" : "idle", error: String(e) });
    }
  },

  async install() {
    if (!pending) return;
    set({ status: "installing", progress: null, error: null });
    let total = 0;
    let got = 0;
    try {
      await pending.downloadAndInstall((ev) => {
        if (ev.event === "Started") total = ev.data.contentLength ?? 0;
        else if (ev.event === "Progress") {
          got += ev.data.chunkLength;
          set({ progress: total ? Math.min(1, got / total) : null });
        }
      });
      // Windows installers close the app themselves; elsewhere restart into the new version
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    } catch (e) {
      set({ status: "error", error: String(e) });
    }
  },

  dismiss: () => set({ dismissed: true }),
}));

const SIX_HOURS = 6 * 60 * 60 * 1000;

/** Check shortly after start-up (not during engine boot) and then every few hours. */
export function startUpdateChecks(): () => void {
  if (!isTauri()) return () => {};
  const run = () => void useUpdate.getState().check();
  const first = setTimeout(run, 10_000);
  const every = setInterval(run, SIX_HOURS);
  return () => {
    clearTimeout(first);
    clearInterval(every);
  };
}
