"""Laster config.yaml og gir stier relativt til prosjektroten."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = ROOT
    return cfg


def raw_dir(cfg: dict, kommunenr: str) -> Path:
    p = ROOT / cfg["paths"]["raw"] / kommunenr
    p.mkdir(parents=True, exist_ok=True)
    return p


def derived_dir(cfg: dict, kommunenr: str) -> Path:
    p = ROOT / cfg["paths"]["derived"] / kommunenr
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path(cfg: dict) -> Path:
    p = ROOT / cfg["paths"]["db"]
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
