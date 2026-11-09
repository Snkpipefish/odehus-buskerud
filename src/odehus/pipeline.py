"""Kjører hele pipelinen (steg 1–7) for én eller flere kommuner.

  python -m odehus.pipeline 3332            # én kommune
  python -m odehus.pipeline alle            # hele Buskerud i briefens rekkefølge (hopper over ferdige)
Logg per kommune i out/logg_<knr>.txt. Status i out/pipeline_status.json.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import traceback

from . import config as C
from .access import steg5
from .buildings import steg1, steg2
from .download import kommuner_i_fylke
from .export import steg7_export
from .imagery import steg6_ndsm
from .rapport import topp
from .score import steg7_score
from .soil import steg4_ar5_tun, steg4_ar50
from .sun import steg3_sol
from .terrain import steg3_terreng

# Briefens rekkefølge: lavlands- og dalkommuner først, bykommunene sist.
REKKEFOLGE = ["3336", "3332", "3334", "3338", "3318", "3316", "3314", "3305", "3320", "3322", "3324", "3328", "3330", "3326",
              "3310", "3312", "3303", "3301"]
STEG = [("steg1", steg1), ("steg2", steg2), ("steg3_terreng", steg3_terreng), ("steg3_sol", steg3_sol),
        ("steg4_ar50", steg4_ar50), ("steg4_ar5", steg4_ar5_tun), ("steg5", steg5), ("steg6_ndsm", steg6_ndsm)]


def _status_fil(cfg):
    return C.ROOT / cfg["paths"]["out"] / "pipeline_status.json"


def kjor_kommune(knr: str, cfg: dict | None = None, fra_steg: str | None = None) -> dict:
    cfg = cfg or C.load()
    status = json.loads(_status_fil(cfg).read_text()) if _status_fil(cfg).exists() else {}
    st = status.setdefault(knr, {})
    for navn, fn in STEG:
        if st.get(navn) == "ok" and not fra_steg:
            continue
        if fra_steg and navn != fra_steg and st.get(navn) == "ok" and STEG.index((navn, fn)) < [s[0] for s in STEG].index(fra_steg):
            continue
        t0 = time.time()
        try:
            fn(knr)
            st[navn] = "ok"
            st[navn + "_sek"] = round(time.time() - t0)
        except Exception as e:  # noqa: BLE001
            st[navn] = f"FEIL: {e}"
            logging.error("%s %s feilet: %s\n%s", knr, navn, e, traceback.format_exc())
            _status_fil(cfg).write_text(json.dumps(status, indent=1, ensure_ascii=False))
            return st
        _status_fil(cfg).write_text(json.dumps(status, indent=1, ensure_ascii=False))
    steg7_score()
    steg7_export(knr)
    topp(knr, 20)
    st["steg7"] = "ok"
    _status_fil(cfg).write_text(json.dumps(status, indent=1, ensure_ascii=False))
    return st


def kjor_alle(cfg: dict | None = None) -> None:
    cfg = cfg or C.load()
    kommuner = kommuner_i_fylke(cfg["fylke"]["nummer"])
    for knr in REKKEFOLGE:
        if knr not in kommuner:
            logging.warning("%s ikke i fylket, hopper over", knr)
            continue
        logging.info("=== %s %s", knr, kommuner[knr])
        st = kjor_kommune(knr, cfg)
        logging.info("=== %s ferdig: %s", knr, {k: v for k, v in st.items() if not k.endswith("_sek")})


if __name__ == "__main__":
    a = sys.argv[1:]
    knr = a[0] if a else "alle"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(C.ROOT / "out" / f"logg_{knr}.txt", encoding="utf-8"), logging.StreamHandler()])
    if knr == "alle":
        kjor_alle()
    else:
        kjor_kommune(knr, fra_steg=a[1] if len(a) > 1 else None)
