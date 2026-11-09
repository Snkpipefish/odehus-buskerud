"""Lager datafila til nettsiden (docs/data.json) fra fylkes-shortlisten.

Tar med kandidater innenfor kriteriene som enten ligger blant de N beste eller er visuelt vurdert
med forfall >= 1. Ingen persondata: bare matrikkelnummer, bruksnavn og åpne beregnede verdier.

Kjør: python -m odehus.web [N]
"""
from __future__ import annotations

import json
import sys
from datetime import date

import pandas as pd

from . import config as C

KOMMUNER = {"3301": "Drammen", "3303": "Kongsberg", "3305": "Ringerike", "3310": "Hole", "3312": "Lier",
            "3314": "Øvre Eiker", "3316": "Modum", "3318": "Krødsherad", "3320": "Flå", "3322": "Nesbyen",
            "3324": "Gol", "3326": "Hemsedal", "3328": "Ål", "3330": "Hol", "3332": "Sigdal", "3334": "Flesberg",
            "3336": "Rollag", "3338": "Nore og Uvdal"}
TYPER = {111: "Enebolig", 113: "Våningshus", 171: "Seterhus/sel", 163: "Våningshus (fritidsbruk)", 162: "Våningshus (fritidsbruk)"}


def _v(x, f=None):
    if pd.isna(x):
        return None
    return f(x) if f else x


def main(n_topp: int = 400) -> dict:
    cfg = C.load()
    out = C.ROOT / cfg["paths"]["out"]
    df = pd.read_csv(out / "buskerud_shortlist.csv")
    inn = df[~df.utenfor_kriterier.fillna(False).astype(bool)]
    vis = (inn.forfall_kilde == "visuell") & (inn.forfall_score.fillna(0) >= 1)
    sel = inn[(inn["rank"] <= n_topp) | vis].sort_values("rank")
    rader = []
    for r in sel.itertuples():
        knr = str(int(r.kommunenr))
        rader.append(dict(
            rank=int(r.rank), score=round(float(r.total), 2), knr=knr, kommune=KOMMUNER.get(knr, knr),
            gnr=_v(r.gnr, int), bnr=_v(r.bnr, int), fnr=_v(r.fnr, int) or 0,
            navn=_v(r.bruksnavn, lambda s: str(s).strip().title()),
            typekode=int(r.type), type=TYPER.get(int(r.type), str(r.type)),
            sefrak=bool(r.sefrak) if not pd.isna(r.sefrak) else False,
            moh=_v(r.moh, lambda x: int(round(x))), aspect=_v(r.aspect_deg, lambda x: int(round(x))),
            slope=_v(r.slope_deg, lambda x: round(float(x), 1)),
            sol_mars=_v(r.soltimer_mars, lambda x: round(float(x), 1)), sol_juli=_v(r.soltimer_juli, lambda x: round(float(x), 1)),
            sol_pct=_v(r.sol_pct, lambda x: int(round(x))),
            innmark=_v(r.innmark_daa, lambda x: int(round(x))), teig_daa=_v(r.teig_daa, lambda x: int(round(x))),
            veg_m=_v(r.veg_m, lambda x: int(round(x))), veg_kat=_v(r.veg_kategori, str),
            naboer=_v(r.naboer_200m, int), hytter=_v(r.hytter_200m, int),
            forfall=_v(r.forfall_score, int), forfall_tekst=_v(r.forfall_begrunnelse, str),
            forfall_kilde=_v(r.forfall_kilde, str),
            lat=round(float(r.lat), 6), lon=round(float(r.lon), 6),
            l_bilder=r.lenke_norgeibilder, l_eiendom=r.lenke_seeiendom, l_kart=r.lenke_norgeskart, l_google=r.lenke_google,
        ))
    meta = dict(generert=str(date.today()), antall=len(rader), kandidater_totalt=int(len(df)),
                innenfor_kriterier=int(len(inn)), visuelt_vurdert=int((df.forfall_kilde == "visuell").sum()),
                kommuner=sorted({(r["knr"], r["kommune"]) for r in rader}, key=lambda t: t[1]))
    d = C.ROOT / "docs"
    d.mkdir(exist_ok=True)
    (d / "data.json").write_text(json.dumps(dict(meta=meta, prospekter=rader), ensure_ascii=False), encoding="utf-8")
    print("docs/data.json:", meta["antall"], "prospekter,", len(meta["kommuner"]), "kommuner")
    return meta


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 400)
