// Display names and color classes for edit reasons and proposal kinds (colors are --c-* tokens in styles.css).
export const KIND_LABEL: Record<string, string> = {
  silence: "Silence",
  filler: "Filler",
  false_start: "False start",
  retake: "Retake",
  manual: "Manual cut",
  agent: "Agent edit",
  speed: "Sped up",
};

/** CSS custom property holding a kind's color. */
export const KIND_VAR: Record<string, string> = {
  silence: "--c-silence",
  filler: "--c-filler",
  false_start: "--c-false",
  retake: "--c-retake",
  manual: "--c-manual",
  agent: "--c-agent",
  speed: "--c-speed",
};

/** Class that sets --c to the kind's color. */
export const kindClass = (k: string) => `c-${k.replace("_", "-")}`;
