"""Tilkomst og isolasjon: avstand til bilveg (NVDB) og antall andre boligbygg innen 200 m.

Kilde (verifisert 2026-11-07): Elveg 2.0 finnes ikke lenger på Geonorge; etterfølgeren «NVDB Vegnett»
distribueres kun som SOSI. Vi bruker derfor Vegvesenets åpne NVDB API Les v4 (NLOD):
  https://nvdbapiles.atlas.vegvesen.no/vegnett/api/v4/veglenkesekvenser/segmentert?kommune=<knr>&srid=5973&antall=1000
Paging via metadata.neste.start (href i svaret peker på gammel sti, så vi bygger URL selv).
Felt: typeVeg_sosi (enkelBilveg, gangOgSykkelveg, ...), vegsystemreferanse.vegsystem.vegkategori (E/R/F/K/P/S),
geometri.wkt (LINESTRING Z, EPSG:5973 = UTM33 + NN2000).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

from . import config as C
from .ingest import connect
from .views import lag_views

log = logging.getLogger(__name__)
NVDB = "https://nvdbapiles.atlas.vegvesen.no/vegnett/api/v4/veglenkesekvenser/segmentert"
BILVEG = {"enkelBilveg", "kanalisertVeg", "rundkjøring", "rampe", "bilferje", "gatetun"}
_ses = requests.Session()
_ses.headers.update({"Accept": "application/json", "X-Client": "odehus-finner"})


def hent_vegnett(cfg: dict, kommunenr: str) -> Path:
    ut = C.raw_dir(cfg, kommunenr) / "nvdb_vegnett.jsonl"
    if ut.exists() and ut.stat().st_size > 1000:
        return ut
    start, n = None, 0
    with open(ut, "w", encoding="utf-8") as f:
        while True:
            p = dict(kommune=kommunenr, srid=5973, antall=1000)
            if start:
                p["start"] = start
            r = _ses.get(NVDB, params=p, timeout=120)
            r.raise_for_status()
            d = r.json()
            for o in d["objekter"]:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
            n += d["metadata"]["returnert"]
            neste = d["metadata"].get("neste")
            if not neste or d["metadata"]["returnert"] == 0:
                break
            start = neste["start"]
            time.sleep(0.2)
    log.info("NVDB: %d segmenter for %s", n, kommunenr)
    return ut


def les_vegnett(path: Path) -> pd.DataFrame:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            vs = (o.get("vegsystemreferanse") or {}).get("vegsystem") or {}
            rows.append(dict(
                referanse=o["referanse"], veglenkesekvensid=o["veglenkesekvensid"], kommunenr=str(o["kommune"]),
                type_veg=o.get("typeVeg_sosi"), vegkategori=vs.get("vegkategori"), fase=vs.get("fase"), vegnummer=vs.get("nummer"),
                kortform=(o.get("vegsystemreferanse") or {}).get("kortform"), lengde_m=o.get("lengde"),
                wkt=o["geometri"]["wkt"],
            ))
    return pd.DataFrame(rows)


def steg5(kommunenr: str, cfg: dict | None = None) -> dict:
    cfg = cfg or C.load()
    kr = cfg["kriterier"]
    t0 = time.time()
    con = connect(C.db_path(cfg))
    df = les_vegnett(hent_vegnett(cfg, kommunenr))
    con.register("_v", df)
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='veg'").fetchone()[0]:
        con.execute("DELETE FROM veg WHERE kommunenr = ?", [kommunenr])
        con.execute("INSERT INTO veg SELECT * EXCLUDE (wkt), ST_Force2D(ST_GeomFromText(wkt)) AS geom FROM _v")
    else:
        con.execute("CREATE TABLE veg AS SELECT * EXCLUDE (wkt), ST_Force2D(ST_GeomFromText(wkt)) AS geom FROM _v")
    con.unregister("_v")
    bilveg = ",".join(f"'{t}'" for t in BILVEG)
    har = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='tilkomst'").fetchone()[0] > 0
    if har:
        con.execute("DELETE FROM tilkomst WHERE bygningid IN (SELECT bygningid FROM kandidat_v1 WHERE kommunenr = ?)", [kommunenr])
    con.execute(f"""
        {"INSERT INTO tilkomst" if har else "CREATE TABLE tilkomst AS"}
        WITH k AS (SELECT bygningid, kommunenr, geom FROM kandidat_v1 WHERE kommunenr = ?),
        naer AS (
            SELECT k.bygningid, v.vegkategori, v.type_veg, v.kortform, ST_Distance(k.geom, v.geom) AS d,
                   row_number() OVER (PARTITION BY k.bygningid ORDER BY ST_Distance(k.geom, v.geom)) AS rn
            FROM k JOIN veg v ON v.kommunenr = k.kommunenr AND v.type_veg IN ({bilveg})
                              AND ST_DWithin(k.geom, v.geom, 3000)
        ),
        off AS (
            SELECT k.bygningid, min(ST_Distance(k.geom, v.geom)) AS d
            FROM k JOIN veg v ON v.kommunenr = k.kommunenr AND v.type_veg IN ({bilveg}) AND v.vegkategori IN ('E','R','F','K')
                              AND ST_DWithin(k.geom, v.geom, 5000)
            GROUP BY k.bygningid
        ),
        nab AS (  -- andre helårsboliger (111–159) og fritidsbygg (161–163) innen 200 m
            SELECT k.bygningid,
                   sum((b.type BETWEEN 111 AND 159)::int) AS n,
                   sum((b.type BETWEEN 161 AND 163)::int) AS h
            FROM k JOIN bygg b ON b.kommunenr = k.kommunenr AND b.bygningid <> k.bygningid
                              AND b.type BETWEEN 111 AND 163 AND ST_DWithin(k.geom, b.geom, 200)
            GROUP BY k.bygningid
        )
        SELECT k.bygningid,
               round(n.d) AS veg_m, n.vegkategori AS veg_kategori, n.type_veg AS veg_type, n.kortform AS veg_ref,
               round(o.d) AS veg_offentlig_m,
               coalesce(nab.n, 0) AS naboer_200m,
               coalesce(nab.h, 0) AS hytter_200m,
               n.vegkategori IN ('P', 'S') AS flagg_privat_veg,
               n.vegkategori = 'S' AS flagg_uten_vinterveg,
               n.d > ? AS flagg_veg_langt,
               n.d > ? AS over_veg_maks
        FROM k LEFT JOIN naer n ON n.bygningid = k.bygningid AND n.rn = 1
               LEFT JOIN off o ON o.bygningid = k.bygningid
               LEFT JOIN nab ON nab.bygningid = k.bygningid
    """, [kommunenr, kr["veg_flagg_m"], kr["veg_maks_m"]])
    lag_views(con)
    n = dict(segmenter=len(df), bilveg=int(df.type_veg.isin(BILVEG).sum()), sek=round(time.time() - t0, 1))
    print("Steg 5:", n)
    print(con.execute("""SELECT count(*) n, round(quantile_cont(veg_m,0.5)) veg_median, max(veg_m) veg_maks,
                                sum(flagg_veg_langt::int) over_150, sum(over_veg_maks::int) over_500,
                                sum(flagg_privat_veg::int) privat, sum(flagg_uten_vinterveg::int) skogsbilveg,
                                round(avg(naboer_200m),1) naboer_snitt, round(avg(hytter_200m),1) hytter_snitt, sum((naboer_200m=0)::int) ingen_naboer,
                                sum((veg_m IS NULL)::int) uten_veg
                         FROM tilkomst WHERE bygningid IN (SELECT bygningid FROM kandidat_v1 WHERE kommunenr = ?)""", [kommunenr]).df().to_string(index=False))
    print(con.execute("SELECT veg_kategori, count(*) FROM tilkomst WHERE bygningid IN (SELECT bygningid FROM kandidat_v1 WHERE kommunenr = ?) GROUP BY 1 ORDER BY 2 DESC", [kommunenr]).fetchall())
    con.close()
    return n


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    steg5(sys.argv[1] if len(sys.argv) > 1 else "3336")
