// Light / dark / follow-the-system appearance. The choice is a per-machine preference kept in localStorage.
import { create } from "zustand";

export type ThemePref = "system" | "light" | "dark";
export type Theme = "light" | "dark";

const KEY = "claudebolt.theme";

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)");
const resolve = (p: ThemePref): Theme => (p === "system" ? (systemDark().matches ? "dark" : "light") : p);

interface ThemeState {
  pref: ThemePref;
  resolved: Theme;
  setPref(p: ThemePref): void;
}

export const useTheme = create<ThemeState>((set) => ({
  pref: readPref(),
  resolved: resolve(readPref()),
  setPref(pref) {
    try {
      localStorage.setItem(KEY, pref);
    } catch {
      /* storage unavailable: the choice lasts for this run */
    }
    set({ pref, resolved: resolve(pref) });
    apply();
  },
}));

function apply() {
  const t = useTheme.getState().resolved;
  document.documentElement.dataset.theme = t;
  document.documentElement.style.colorScheme = t;
}

/** Call once before the first render so the page never flashes the wrong theme. */
export function initTheme() {
  apply();
  systemDark().addEventListener("change", () => {
    if (useTheme.getState().pref !== "system") return;
    useTheme.setState({ resolved: resolve("system") });
    apply();
  });
}
