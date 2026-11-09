"""Visuell forfallsvurdering (gjort av Claude i nettleseren mot norgeibilder.no, nyeste ortofoto).

  python -m odehus.vurder liste 3336 300        -> out/vurder_3336.json med kø (rank, bygningid, x, y, navn, url)
  python -m odehus.vurder sett 3336 <bygningid> <score> "<begrunnelse>" [...flere tripler]
  python -m odehus.vurder skriv 3336            -> oppdaterer tabell forfall (forfall_kilde='visuell') og score/eksport
"""
from __future__ import annotations

import json
import sys

from . import config as C
from .ingest import connect


def _fil(cfg, knr):
    return C.ROOT / cfg["paths"]["out"] / f"vurder_{knr}.json"


def liste(knr: str, n: int = 300):
    cfg = C.load()
    con = connect(C.db_path(cfg))
    rader = con.execute("""SELECT rank, bygningid, round(x), round(y), bruksnavn, gnr, bnr, type, forfall_score, gjengroing_tun_pct, bygg_hoyde_m, lat, lon
                           FROM kandidat WHERE kommunenr=? AND NOT utenfor_kriterier ORDER BY rank LIMIT ?""", [knr, n]).fetchall()
    con.close()
    d = json.loads(_fil(cfg, knr).read_text()) if _fil(cfg, knr).exists() else {"vurdert": {}}
    d["ko"] = [dict(rank=r[0], bygningid=r[1], x=r[2], y=r[3], navn=r[4], gnr=r[5], bnr=r[6], type=r[7], proxy=r[8], gjengroing=r[9], hoyde=r[10],
                    lat=r[11], lon=r[12],
                    url=f"https://norgeibilder.no/?wkid=25833&is3d=false&xmin={r[2]-170:.0f}&xmax={r[2]+170:.0f}&ymin={r[3]-125:.0f}&ymax={r[3]+125:.0f}")
               for r in rader]
    _fil(cfg, knr).write_text(json.dumps(d, ensure_ascii=False, indent=0))
    print(len(d["ko"]), "i kø,", len(d["vurdert"]), "vurdert")


def neste(knr: str, n: int = 1):
    cfg = C.load()
    d = json.loads(_fil(cfg, knr).read_text())
    ut = [k for k in d["ko"] if str(k["bygningid"]) not in d["vurdert"]][:n]
    for k in ut:
        print(f"{k['rank']}|{k['bygningid']}|{k['navn']} {k['gnr']}/{k['bnr']} type {k['type']}|proxy {k['proxy']} gjengr {k['gjengroing']}% h {k['hoyde']}|{k['lat']}, {k['lon']}")


def sett(knr: str, args: list[str]):
    cfg = C.load()
    d = json.loads(_fil(cfg, knr).read_text())
    for i in range(0, len(args), 3):
        bid, score, tekst = args[i], int(args[i + 1]), args[i + 2]
        d["vurdert"][str(bid)] = dict(score=score, tekst=tekst)
    _fil(cfg, knr).write_text(json.dumps(d, ensure_ascii=False, indent=0))
    print(len(d["vurdert"]), "vurdert av", len(d["ko"]))


def skriv(knr: str):
    from .export import steg7_export
    from .rapport import topp
    from .score import steg7_score

    cfg = C.load()
    d = json.loads(_fil(cfg, knr).read_text())
    con = connect(C.db_path(cfg))
    con.execute("ALTER TABLE forfall ADD COLUMN IF NOT EXISTS forfall_proxy INTEGER")
    con.execute("ALTER TABLE forfall ADD COLUMN IF NOT EXISTS forfall_visuell INTEGER")
    con.execute("ALTER TABLE forfall ADD COLUMN IF NOT EXISTS forfall_visuell_tekst VARCHAR")
    for kol in ("img_old", "img_new", "img_old_aar", "img_new_aar"):  # ble opprettet som NULL-type i steg 6
        if con.execute("SELECT data_type FROM information_schema.columns WHERE table_name='forfall' AND column_name=?", [kol]).fetchone()[0] == '"NULL"':
            con.execute(f"ALTER TABLE forfall DROP COLUMN {kol}")
            con.execute(f"ALTER TABLE forfall ADD COLUMN {kol} VARCHAR")
    con.execute("UPDATE forfall SET forfall_proxy = forfall_score WHERE forfall_proxy IS NULL")
    for bid, v in d["vurdert"].items():
        con.execute("""UPDATE forfall SET forfall_visuell=?, forfall_visuell_tekst=?, forfall_score=?,
                       forfall_begrunnelse=?, forfall_kilde='visuell', img_new_aar='nyeste ortofoto norgeibilder.no' WHERE bygningid=?""",
                    [v["score"], v["tekst"], v["score"], v["tekst"], int(bid)])
    n = con.execute("SELECT count(*) FROM forfall WHERE forfall_kilde='visuell'").fetchone()[0]
    con.close()
    print(n, "visuelle vurderinger i DB")
    steg7_score()
    steg7_export(knr)
    topp(knr, 20)


if __name__ == "__main__":
    cmd, knr, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
    {"liste": lambda: liste(knr, int(rest[0]) if rest else 300), "neste": lambda: neste(knr, int(rest[0]) if rest else 1),
     "sett": lambda: sett(knr, rest), "skriv": lambda: skriv(knr)}[cmd]()
