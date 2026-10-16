"""Settings models and app-data paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from platformdirs import user_cache_path, user_config_path
from pydantic import BaseModel, Field

APP = "claudebolt"


def cache_dir() -> Path:
    p = Path(os.environ.get("CLAUDEBOLT_CACHE") or user_cache_path(APP, appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = Path(os.environ.get("CLAUDEBOLT_MODELS") or cache_dir() / "models")
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    p = Path(os.environ.get("CLAUDEBOLT_CONFIG") or user_config_path(APP, appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p / "settings.json"


def daemon_file() -> Path:
    return cache_dir() / "daemon.json"


class DetectionSettings(BaseModel):
    mode: Literal["rms", "vad", "both"] = "rms"
    threshold: float | Literal["auto"] = -35.0
    grace: float = 0.5
    pad_left: float = 0.01
    pad_right: float = 0.15
    min_keep: float = 0.75
    snap_window: float = 0.02
    silence_action: Literal["cut", "speed"] = "cut"
    speed_rate: float = 3.0
    speed_min: float = 0.5
    speed_max: float = 1e9
    mute_speed: bool = False
    keep_edges: bool = False
    combine: Literal["any", "primary"] = "any"


class CleanupSettings(BaseModel):
    fillers: list[str] = Field(
        default_factory=lambda: [
            "um", "uh", "er", "ah", "hmm", "mm", "like", "you know", "i mean",
            "sort of", "kind of", "basically", "actually", "literally", "right", "so",
        ]
    )
    kinds: list[str] = Field(default_factory=lambda: ["filler", "false_start", "retake"])
    look_ahead: int = 10
    similarity: float = 0.8
    min_confidence: float = 0.0


class RenderSettings(BaseModel):
    container: str | None = None  # None -> same as source
    vcodec: str = "libx264"
    acodec: str | None = None
    crf: int = 18
    bitrate: str | None = None
    encoder_pref: str = "libx264"  # "auto" probes GPU encoders first
    fade_ms: float = 8.0
    crossfade_ms: float = 0.0
    zoom_mode: Literal["none", "alternate"] = "none"
    zoom: float = 1.25
    split_concat: bool | None = None  # None -> automatic
    preset: str = "medium"


class AppSettings(BaseModel):
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    cleanup: CleanupSettings = Field(default_factory=CleanupSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    output_dir: str | None = None
    whisper_model: str = "small.en"


def load_settings() -> AppSettings:
    p = settings_path()
    if p.exists():
        try:
            return AppSettings.model_validate_json(p.read_text("utf-8"))
        except Exception:
            pass
    return AppSettings()


def save_settings(s: AppSettings) -> None:
    p = settings_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s.model_dump(), indent=2), "utf-8")
    tmp.replace(p)
