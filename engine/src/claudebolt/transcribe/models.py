"""Whisper model catalog + on-demand download (Hugging Face hub, integrity-checked by the hub)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..config import models_dir

CATALOG: dict[str, dict] = {
    "tiny.en": {"repo": "Systran/faster-whisper-tiny.en", "size_mb": 75, "note": "tests / drafts"},
    "base.en": {"repo": "Systran/faster-whisper-base.en", "size_mb": 145, "note": "fast drafts"},
    "small.en": {"repo": "Systran/faster-whisper-small.en", "size_mb": 480, "note": "default"},
    "large-v3-turbo": {"repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "size_mb": 1600,
                       "note": "best quality, wants a GPU"},
    "tiny": {"repo": "Systran/faster-whisper-tiny", "size_mb": 75, "note": "multilingual"},
    "base": {"repo": "Systran/faster-whisper-base", "size_mb": 145, "note": "multilingual"},
    "small": {"repo": "Systran/faster-whisper-small", "size_mb": 480, "note": "multilingual"},
}


class ModelError(RuntimeError):
    pass


def model_dir(name: str) -> Path:
    return models_dir() / f"whisper-{name}"


def installed(name: str) -> bool:
    return (model_dir(name) / "model.bin").exists()


def list_models() -> list[dict]:
    return [{"name": n, **{k: v for k, v in m.items() if k != "repo"}, "installed": installed(n)}
            for n, m in CATALOG.items()]


def download(name: str, on_progress: Callable[[float], None] | None = None) -> Path:
    if name not in CATALOG:
        raise ModelError(f"unknown model {name!r}; choose one of {', '.join(CATALOG)}")
    if installed(name):
        return model_dir(name)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise ModelError("faster-whisper not installed: uv sync --extra whisper") from e
    d = model_dir(name)
    snapshot_download(CATALOG[name]["repo"], local_dir=str(d),
                      allow_patterns=["config.json", "model.bin", "tokenizer.json",
                                      "vocabulary.*", "preprocessor_config.json"])
    if on_progress:
        on_progress(1.0)
    return d


def delete(name: str) -> bool:
    import shutil

    d = model_dir(name)
    if d.exists():
        shutil.rmtree(d)
        return True
    return False
