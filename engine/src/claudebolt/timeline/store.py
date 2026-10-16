"""Project file load/save (atomic)."""

from __future__ import annotations

import os
from pathlib import Path

from .model import Project

SUFFIX = ".claudebolt.json"


def default_path(media: str | Path) -> Path:
    m = Path(media)
    return m.with_name(m.name + SUFFIX)


def save(p: Project, path: str | Path | None = None) -> Path:
    target = Path(path or p.project_path or default_path(p.primary.path))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(p.model_dump_json(indent=1), "utf-8")
    os.replace(tmp, target)
    p.project_path = str(target)
    return target


def load(path: str | Path) -> Project:
    p = Project.model_validate_json(Path(path).read_text("utf-8"))
    p.project_path = str(path)
    return p
