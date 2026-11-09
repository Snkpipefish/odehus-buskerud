"""Steg 1-rapport og bygningsfiltrering.

Kjør:  python -m odehus.buildings 3336
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

from pyproj import Transformer

from . import config as C
from .download import hent_alle_matrikkel, kommuner_i_fylke
from .ingest import connect, last_kommune

log = logging.getLogger(__name__)
_til_wgs84 = Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True)


def kodeliste_bygningstype() -> dict[int, str]:
    p = Path(__file__).parent / "kodelister" / "bygningstype.csv"
    with open(p, encoding="utf-8") as f:
        return {int(r["kode"]): r["beskrivelse"] for r in csv.DictReader(f)}


def lenker(x: float, y: float) -> dict[str, str]:
    lon, lat = _til_wgs84.transform(x, y)
    return dict(
        lat=round(lat, 6),
        lon=round(lon, 6),
        norgeskart=f"https://norgeskart.no/#!?project=norgeskart&layers=1002&zoom=16&lat={y:.1f}&lon={x:.1f}&markerLat={y:.1f}&markerLon={x:.1f}",
        google=f"https://www.google.com/maps/@{lat:.6f},{lon:.6f},200m/data=!3m1!1e3",
        norgeibilder=f"https://norgeibilder.no/?wkid=25833&is3d=false&xmin={x-150:.0f}&xmax={x+150:.0f}&ymin={y-100:.0f}&ymax={y+100:.0f}",
    )


def steg1(kommunenr: str, cfg: dict | None = None, seed: int = 42) -> None:
    cfg = cfg or C.load()
    kommuner = kommuner_i_fylke(cfg["fylke"]["nummer"])
    if kommunenr not in kommuner:
        sys.exit(f"{kommunenr} er ikke i fylke {cfg['fylke']['nummer']}: {sorted(kommuner)}")
    navn = kommuner[kommunenr]
    print(f"Kommune {kommunenr} {navn} (fylke {cfg['fylke']['navn']}, {len(kommuner)} kommuner)")

    filer = hent_alle_matrikkel(cfg, kommunenr, navn)
    con = connect(C.db_path(cfg))
    n = last_kommune(con, kommunenr, filer)
    print("Rader lastet:", n)

    typer = kodeliste_bygningstype()
    onsket = cfg["kriterier"]["bygningstyper"]
    print("\nBygg per type (topp 15) for", navn)
    for typ, ant, sef in con.execute(
        "SELECT type, count(*), sum(sefrak::int) FROM bygg WHERE kommunenr=? GROUP BY type ORDER BY 2 DESC LIMIT 15",
        [kommunenr],
    ).fetchall():
        mark = " <==" if typ in onsket else ""
        print(f"  {typ:>4}  {ant:>5}  sefrak={sef:<4} {typer.get(typ, '?')[:60]}{mark}")

    tot = con.execute(
        f"SELECT count(*) FROM bygg WHERE kommunenr=? AND type IN ({','.join(map(str, onsket))})", [kommunenr]
    ).fetchone()[0]
    print(f"\nSELECT count(*) FROM bygg WHERE type IN {tuple(onsket)}  ->  {tot}")

    print("\nStatus-fordeling for ønskede typer:")
    for st, ant in con.execute(
        f"SELECT status, count(*) FROM bygg WHERE kommunenr=? AND type IN ({','.join(map(str, onsket))}) GROUP BY 1 ORDER BY 2 DESC",
        [kommunenr],
    ).fetchall():
        print(f"  {st:<4} {ant}")

    uten_teig = con.execute(
        "SELECT count(*) FROM bygg WHERE kommunenr=? AND teig_id IS NULL", [kommunenr]
    ).fetchone()[0]
    print(f"\nBygg uten teig-treff: {uten_teig} av {n['bygg']}")

    print(f"\n10 tilfeldige våningshus (113), seed={seed} – sjekk mot norgeskart.no:")
    rader = con.execute(
        f"""SELECT * FROM (
                SELECT bygningsnummer, gnr, bnr, fnr, bruksnavn, status, sefrak, x, y, teig_areal_m2
                FROM bygg WHERE kommunenr=? AND type=113
            ) USING SAMPLE reservoir(10 ROWS) REPEATABLE ({seed})
            ORDER BY gnr, bnr""",
        [kommunenr],
    ).fetchall()
    for bnr_, gnr, bnr, fnr, navn_, st, sef, x, y, areal in rader:
        L = lenker(x, y)
        print(
            f"  bygg {bnr_}  {kommunenr}-{gnr}/{bnr}" + (f"/{fnr}" if fnr else "") +
            f"  {navn_ or ''}  status={st} sefrak={sef} teig={areal/1000 if areal else 0:.0f} daa"
        )
        print(f"      UTM33 E={x:.1f} N={y:.1f}   WGS84 {L['lat']},{L['lon']}")
        print(f"      {L['norgeskart']}")
    con.close()




# ---------------------------------------------------------------- Steg 2
def steg2(kommunenr: str, cfg: dict | None = None) -> dict:
    """Filtrerer bygg på type, status og moh, kobler teig-geometri -> tabell kandidat_v1.

    Byggeår finnes ikke i åpne data, så alle bygg beholdes uansett alder (jf. briefen:
    «ta vare på alle våningshus ... selv om byggeår mangler»). Innmark kommer i steg 4.
    """
    import time

    from .download import hoyde_punkter

    cfg = cfg or C.load()
    kr = cfg["kriterier"]
    typer = kr["bygningstyper"]
    ekskl = kr["ekskluder_status"]
    t0 = time.time()
    con = connect(C.db_path(cfg))
    typer_sql = ",".join(map(str, typer))
    ekskl_sql = ",".join(f"'{s}'" for s in ekskl)

    n = {}
    n["bygg"] = con.execute("SELECT count(*) FROM bygg WHERE kommunenr=?", [kommunenr]).fetchone()[0]
    n["etter_type"] = con.execute(
        f"SELECT count(*) FROM bygg WHERE kommunenr=? AND type IN ({typer_sql})", [kommunenr]
    ).fetchone()[0]
    n["etter_status"] = con.execute(
        f"SELECT count(*) FROM bygg WHERE kommunenr=? AND type IN ({typer_sql}) AND status NOT IN ({ekskl_sql})",
        [kommunenr],
    ).fetchone()[0]

    # moh for alle bygg som har passert type+status (cachet API-oppslag)
    pts = con.execute(
        f"SELECT bygningid, x, y FROM bygg WHERE kommunenr=? AND type IN ({typer_sql}) AND status NOT IN ({ekskl_sql})",
        [kommunenr],
    ).fetchall()
    h = hoyde_punkter(cfg, kommunenr, [(x, y) for _, x, y in pts])
    import pandas as pd

    moh = pd.DataFrame(
        [dict(bygningid=b, moh=h[(x, y)]["z"], hoyde_kilde=h[(x, y)]["datakilde"], hoyde_terreng=h[(x, y)]["terreng"])
         for b, x, y in pts]
    )
    con.register("_moh", moh)
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='bygg_moh'").fetchone()[0]:
        con.execute("DELETE FROM bygg_moh WHERE bygningid IN (SELECT bygningid FROM _moh)")
        con.execute("INSERT INTO bygg_moh SELECT * FROM _moh")
    else:
        con.execute("CREATE TABLE bygg_moh AS SELECT * FROM _moh")
    con.unregister("_moh")

    har_kv1 = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='kandidat_v1'").fetchone()[0] > 0
    if har_kv1:
        con.execute("DELETE FROM kandidat_v1 WHERE kommunenr = ?", [kommunenr])
    con.execute(
        f"""
        {"INSERT INTO kandidat_v1" if har_kv1 else "CREATE TABLE kandidat_v1 AS"}
        SELECT b.bygningid, b.bygningsnummer, b.kommunenr, b.type, b.byggeaar, b.status,
               b.sefrak, b.sefrak_minne_id, b.kulturminne,
               b.x, b.y, b.geom,
               m.moh, m.hoyde_kilde, m.hoyde_terreng,
               b.teig_id, b.gnr, b.bnr, b.fnr, b.bruksnavn,
               t.areal_m2 / 1000.0 AS teig_daa, t.flere_matrikkelenheter AS teig_flere_me,
               t.matrikkelenhetstype, b.teig_me_match,
               b.status = 'GR'            AS flagg_godkjent_revet,
               b.type IN (162, 163)       AS flagg_fritidsbruk,
               b.antall_bruksenheter, b.adresse_ids,
               t.geom AS teig_geom
        FROM bygg b
        JOIN teig t ON t.teig_id = b.teig_id
        LEFT JOIN bygg_moh m ON m.bygningid = b.bygningid
        WHERE b.kommunenr = ?
          AND b.type IN ({typer_sql})
          AND b.status NOT IN ({ekskl_sql})
          AND (m.moh IS NULL OR m.moh <= ?)
        """,
        [kommunenr, kr["moh_maks"]],
    )
    n["kandidat_v1"] = con.execute("SELECT count(*) FROM kandidat_v1 WHERE kommunenr=?", [kommunenr]).fetchone()[0]
    n["fjernet_moh"] = n["etter_status"] - n["kandidat_v1"]
    n["sek"] = round(time.time() - t0, 1)

    print(f"Steg 2 {kommunenr}: {n}")
    print("Per type i kandidat_v1:")
    for typ, ant, sef, mohmin, mohmax in con.execute(
        "SELECT type, count(*), sum(sefrak::int), min(moh), max(moh) FROM kandidat_v1 WHERE kommunenr=? GROUP BY 1 ORDER BY 2 DESC",
        [kommunenr],
    ).fetchall():
        print(f"  {typ}: {ant}  sefrak={sef}  moh {mohmin:.0f}–{mohmax:.0f}")
    print("Flagg: godkjent revet =", con.execute("SELECT count(*) FROM kandidat_v1 WHERE flagg_godkjent_revet").fetchone()[0],
          "| fritidsbruk =", con.execute("SELECT count(*) FROM kandidat_v1 WHERE flagg_fritidsbruk").fetchone()[0])
    print("Fjernet pga moh > %s:" % kr["moh_maks"], con.execute(
        f"SELECT type, count(*) FROM bygg b JOIN bygg_moh m USING(bygningid) WHERE b.kommunenr=? AND m.moh > ? GROUP BY 1",
        [kommunenr, kr["moh_maks"]]).fetchall())
    con.close()
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = sys.argv[1:]
    steg = args[0] if args and args[0].startswith("steg") else "steg1"
    knr = next((a for a in args if a.isdigit()), C.load()["test_kommune"])
    {"steg1": steg1, "steg2": steg2}[steg](knr)
