export interface Seg {
  src_start: number;
  src_end: number;
  out_start: number;
  out_end: number;
  op: "keep" | "remove" | "speed";
  reason: string | null;
  locked: boolean;
  speed?: number;
  zoom?: number;
}

export interface Describe {
  id: string;
  version: number;
  project_path: string | null;
  sources: { id: string; path: string; kind: "video" | "audio"; duration: number }[];
  duration: number;
  output_duration: number;
  has_transcript: boolean;
  warnings: string[];
}

export interface Word {
  i: number;
  text: string;
  start: number;
  end: number;
  removed: boolean;
}

export interface Proposal {
  id: string;
  kind: "filler" | "false_start" | "retake";
  start: number;
  end: number;
  word_range: [number, number] | null;
  text: string;
  confidence: number;
  status: "pending" | "accepted" | "rejected";
  note: string;
}

export interface Summary {
  source_duration: number;
  output_duration: number;
  percent_removed: number;
  removed_seconds: number;
  threshold_db?: number;
}

export interface Detection {
  mode: "rms" | "vad" | "both";
  threshold: number | "auto";
  grace: number;
  pad_left: number;
  pad_right: number;
  min_keep: number;
  silence_action: "cut" | "speed";
  speed_rate: number;
}

export interface Job {
  job_id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  result?: Record<string, unknown>;
  error?: string;
}

export interface ActivityItem {
  id: number;
  actor: string;
  ops: string[];
  version: number;
  at: number;
}

export interface EngineEvent {
  type: string;
  project?: string;
  version?: number;
  op?: string[];
  actor?: string;
  job?: string;
  progress?: number;
  result?: Record<string, unknown>;
  error?: string;
}
