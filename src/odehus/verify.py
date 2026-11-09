"""Automatisk stikkprøve: sjekker at gnr/bnr fra vår teig-kobling stemmer med Kartverkets
eiendoms-API (https://api.kartverket.no/eiendom/v1/punkt). Skriver en rapport med lenker
til norgeskart.no, norgeibilder.no og Google Maps for manuell kontroll.

Kjør:  python -m odehus.verify 3336 [antall] [seed]
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

import requests

from . import config as C
from .buildings import lenker
from .ingest import connect

PUNKT_API = "https://api.kartverket.no/eiendom/v1/punkt"


def matrikkel_ved_punkt(x: float, y: float) -> list[tuple[int, int, int]]:
    """(gnr, bnr, fnr) for alle matrikkelenheter på teigen som dekker punktet (EPSG:25833)."""
    r = requests.get(
        PUNKT_API,
        params=dict(nord=y, ost=x, koordsys=25833, radius=1),
        timeout=30,
        headers={"User-Agent": "odehus-finner/0.1"},
    )
    r.raise_for_status()
    return [(e["gardsnummer"], e["bruksnummer"], e.get("festenummer", 0)) for e in r.json().get("eiendom", [])]


def stikkprover(kommunenr: str, antall: int = 10, seed: int = 42, type_: int = 113) -> Path:
    cfg = C.load()
    con = connect(C.db_path(cfg))
    rader = con.execute(
        f"""SELECT * FROM (
                SELECT bygningsnummer, gnr, bnr, fnr, bruksnavn, status, sefrak, x, y, teig_areal_m2
                FROM bygg WHERE kommunenr=? AND type=?
            ) USING SAMPLE reservoir({antall} ROWS) REPEATABLE ({seed}) ORDER BY gnr, bnr""",
        [kommunenr, type_],
    ).fetchall()
    con.close()

    linjer = [
        f"# Stikkprøver steg 1 – kommune {kommunenr}, bygningstype {type_}, seed {seed}",
        f"Generert {date.today()}. Kolonnen «API» er gnr/bnr fra Kartverkets eiendoms-API på samme punkt.",
        "",
        "| # | Bygg | Vår gnr/bnr | API | Bruksnavn | Status | SEFRAK | Teig daa | WGS84 | Kart |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    ok = 0
    for i, (bn, gnr, bnr, fnr, navn, st, sef, x, y, areal) in enumerate(rader, 1):
        api = matrikkel_ved_punkt(x, y)
        treff = any(g == gnr and b == bnr for g, b, _ in api)
        ok += treff
        L = lenker(x, y)
        api_txt = ", ".join(f"{g}/{b}" + (f"/{f}" if f else "") for g, b, f in api) or "–"
        linjer.append(
            f"| {i} | {bn} | {gnr}/{bnr}" + (f"/{fnr}" if fnr else "") + f" | {api_txt} {'✅' if treff else '❌'} | {navn or ''} | {st} | {'ja' if sef else ''} | {areal/1000:.0f} | {L['lat']}, {L['lon']} | "
            f"[norgeskart]({L['norgeskart']}) · [flyfoto]({L['norgeibilder']}) · [google]({L['google']}) |"
        )
        time.sleep(0.3)
    linjer += ["", f"**{ok}/{len(rader)} stemmer med Kartverkets API.**"]
    out = C.ROOT / cfg["paths"]["out"] / f"steg1_{kommunenr}_stikkprover.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(linjer) + "\n", encoding="utf-8")
    print("\n".join(linjer))
    print("\nskrevet til", out)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    stikkprover(a[0] if a else C.load()["test_kommune"], int(a[1]) if len(a) > 1 else 10, int(a[2]) if len(a) > 2 else 42)
