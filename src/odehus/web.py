"""Lager datafila til nettsiden (docs/data.json) fra fylkes-shortlisten.

Tar med kandidater innenfor kriteriene med forfall >= 1 som enten ligger blant de N beste eller er visuelt
vurdert. Tun som er sett og er i bruk (forfall 0) tas ut. Ingen persondata: bare matrikkelnummer, bruksnavn og åpne beregnede verdier.

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


def _kortnavn() -> dict[int, str]:
    """Kort norsk navn per bygningstype fra kodelista («English: Norsk; forklaring»)."""
    from .buildings import kodeliste_bygningstype

    ut = {}
    for kode, tekst in kodeliste_bygningstype().items():
        t = tekst.split(": ", 1)[1] if ": " in tekst.split(";")[0] else tekst
        ut[kode] = t.split(";")[0].split(".")[0].strip()[:28]
    ut.update({111: "Enebolig", 112: "Enebolig m/hybel", 113: "Våningshus", 121: "Tomannsbolig", 122: "Tomannsbolig",
               123: "Våningshus (to boliger)", 124: "Våningshus (to boliger)", 131: "Rekkehus", 161: "Hytte/fritidsbolig",
               162: "Helårsbolig som fritidsbolig", 163: "Våningshus som fritidsbolig", 171: "Seterhus/sel",
               172: "Skogs-/utmarkskoie", 181: "Garasje/uthus/anneks", 182: "Garasje/uthus (fritid)", 183: "Naust/båthus",
               193: "Boligbrakke", 241: "Driftsbygning (dyr/lager/silo)", 243: "Veksthus", 249: "Annen landbruksbygning",
               231: "Lagerhall", 239: "Annen lagerbygning", 290: "Annen industri/lager"})
    return ut


def _legg_til_bygg(cfg: dict, rader: list[dict], radius_m: float = 160.0) -> None:
    """Legger inn alle matrikkelens bygningspunkter innen radius_m rundt hvert prospekt:
    [dx_m øst, dy_m nord, typekode, kortnavn, er_prospektet]. Viser hvor bygningene *skal* stå."""
    from .ingest import connect

    navn = _kortnavn()
    con = connect(C.db_path(cfg))
    pos = {r[0]: r[1:] for r in con.execute("SELECT rank, bygningid, x, y FROM kandidat WHERE rank <= ?",
                                             [max(p["rank"] for p in rader)]).fetchall()}
    for p in rader:
        bid, x0, y0 = pos.get(p["rank"], (None, None, None))
        if bid is None:
            p["bygg"] = []
            continue
        rows = con.execute(
            "SELECT bygningid, type, x, y, status FROM bygg WHERE kommunenr=? AND x BETWEEN ? AND ? AND y BETWEEN ? AND ?",
            [p["knr"], x0 - radius_m, x0 + radius_m, y0 - radius_m, y0 + radius_m]).fetchall()
        p["bygg"] = [[round(x - x0, 1), round(y - y0, 1), int(t), navn.get(int(t), str(t)), b == bid]
                     for b, t, x, y, st in rows if ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5 <= radius_m]
    con.close()


def main(n_topp: int = 400) -> dict:
    cfg = C.load()
    out = C.ROOT / cfg["paths"]["out"]
    df = pd.read_csv(out / "buskerud_shortlist.csv")
    inn = df[~df.utenfor_kriterier.fillna(False).astype(bool)]
    vis = (inn.forfall_kilde == "visuell") & (inn.forfall_score.fillna(0) >= 1)
    # Tun som er sett (flyfoto/satellitt) og er i bruk (forfall 0) tas ut: målet er steder å restaurere eller bygge nytt.
    # Laser-rader uten tegn til forfall tas også ut. Igjen står: sett med forfall >= 1, og laser-rader med forfall >= 1 i topp N.
    sel = inn[((inn["rank"] <= n_topp) | vis) & (inn.forfall_score.fillna(0) >= 1)].sort_values("rank")
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
    _legg_til_bygg(cfg, rader)
    for p in rader:  # satellittutsnitt fra odehus.satbilder, hvis laget
        sti = f"img/{p['knr']}-{p['gnr']}-{p['bnr']}-{p['rank']}.jpg"
        if (C.ROOT / "docs" / sti).exists():
            p["img"] = sti
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
