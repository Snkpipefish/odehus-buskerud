"""Jord: innmark per teig.

Kilder (verifisert 2026-11-07):
- FKB-AR5 som datasett er Norge digitalt-begrenset (rolle nd.filnedlasting.fkb). Brukes IKKE som nedlasting.
- AR50 (NIBIO, NLOD): WFS https://wfs.nibio.no/cgi-bin/ar50_2  typeNames=ms:AR50, EPSG:25833.
  Attributter: arealtype (10 bebygd, 20 jordbruk, 30 skog, 50 åpen fastmark, 60 myr, 81 ferskvann),
  jordbruk (24 = dyrka mark, 25 = innmarksbeite, 98 = ikke relevant), skogbonitet, treslag.
  Minste flate ~15 daa, så små jorder rundt setre kan mangle.
- AR5 via NIBIO «Arealressurskart - FKB-AR5 - Forvaltning - 2 - WMS» (NLOD 2.0, åpen):
  GetFeatureInfo på lag AR5flater gir AR5-flaten (artype, areal_da, geometri) i punktet.
  Laget har MaxScaleDenominator 50000, så oppslag må gjøres med ≤ ~10 m/px. Brukes punktvis rundt tunet.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from lxml import etree
from shapely.geometry import MultiPolygon, Point, Polygon

from . import config as C
from .ingest import _child, _local, _ring, connect, iter_features
from .views import lag_views

log = logging.getLogger(__name__)

AR50_WFS = "https://wfs.nibio.no/cgi-bin/ar50_2"
AR5_WMS = "https://wms.nibio.no/cgi-bin/ar5forvaltning2"
AR5_INNMARK = {21: "fulldyrka", 22: "overflatedyrka", 23: "innmarksbeite"}
AR50_INNMARK = {24: "dyrka", 25: "innmarksbeite"}
_ses = requests.Session()
TRAADER = 4


# ---------------------------------------------------------------- AR50
def hent_ar50(cfg: dict, kommunenr: str, bbox: tuple[float, float, float, float]) -> Path:
    ut = C.raw_dir(cfg, kommunenr) / "ar50.gml"
    if ut.exists() and ut.stat().st_size > 10_000:
        return ut
    x0, y0, x1, y1 = bbox
    r = _ses.get(AR50_WFS, params=dict(Service="WFS", version="2.0.0", Request="GetFeature", typeNames="ms:AR50",
                                       srsName="EPSG:25833", bbox=f"{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},EPSG:25833",
                                       count=100000), timeout=600)
    r.raise_for_status()
    ut.write_bytes(r.content)
    return ut


def _gml_polygon(el) -> Polygon | MultiPolygon | None:
    """Polygon/MultiSurface (GML 3.2 fra MapServer) -> shapely."""
    polys = []
    for p in el.iter():
        if _local(p.tag) != "Polygon":
            continue
        ext, ints = None, []
        for sub in p:
            ln = _local(sub.tag)
            if ln == "exterior":
                ext = _ring(sub)
            elif ln == "interior":
                ints.append(_ring(sub))
        if ext and len(ext) >= 4:
            polys.append(Polygon(ext, [r for r in ints if len(r) >= 4]))
    if not polys:
        return None
    g = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    return g if g.is_valid else g.buffer(0)


def les_ar50(path: Path) -> pd.DataFrame:
    rows = []
    for el in iter_features(path, {"AR50"}):
        g = _gml_polygon(el)
        if g is None:
            continue
        def t(n):
            e = _child(el, n)
            return e.text.strip() if e is not None and e.text else None
        rows.append(dict(lokalid=int(t("lokalid")), arealtype=int(t("arealtype") or 0), jordbruk=int(t("jordbruk") or 0),
                         skogbonitet=int(t("skogbonitet") or 0), treslag=int(t("treslag") or 0),
                         areal_daa=g.area / 1000, geom_wkb=g.wkb))
    return pd.DataFrame(rows)


def steg4_ar50(kommunenr: str, cfg: dict | None = None) -> dict:
    """AR50 ∩ teig for alle teiger med kandidater: daa dyrka (24), innmarksbeite (25) og sum."""
    cfg = cfg or C.load()
    t0 = time.time()
    con = connect(C.db_path(cfg))
    x0, y0, x1, y1 = con.execute("SELECT min(x)-3000, min(y)-3000, max(x)+3000, max(y)+3000 FROM kandidat_v1 WHERE kommunenr=?", [kommunenr]).fetchall()[0]
    df = les_ar50(hent_ar50(cfg, kommunenr, (x0, y0, x1, y1)))
    con.register("_a", df)
    con.execute("CREATE OR REPLACE TABLE ar50 AS SELECT lokalid, arealtype, jordbruk, skogbonitet, treslag, areal_daa, ST_GeomFromWKB(geom_wkb) AS geom FROM _a")
    con.unregister("_a")
    har = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='teig_ar50'").fetchone()[0] > 0
    if har:
        con.execute("DELETE FROM teig_ar50 WHERE teig_id IN (SELECT teig_id FROM teig WHERE kommunenr = ?)", [kommunenr])
    con.execute(f"""
        {"INSERT INTO teig_ar50" if har else "CREATE TABLE teig_ar50 AS"}
        WITH teiger AS (SELECT DISTINCT t.teig_id, t.geom FROM teig t JOIN kandidat_v1 k USING(teig_id) WHERE k.kommunenr = ?),
        snitt AS (
            SELECT t.teig_id, a.jordbruk, a.arealtype,
                   ST_Area(ST_Intersection(t.geom, a.geom)) / 1000.0 AS daa
            FROM teiger t JOIN ar50 a ON ST_Intersects(t.geom, a.geom)
        )
        SELECT s.teig_id,   -- cappet til teigarealet: AR50-flater kan overlappe litt
               round(least(sum(CASE WHEN jordbruk = 24 THEN s.daa ELSE 0 END), ta.daa), 1) AS ar50_dyrka_daa,
               round(least(sum(CASE WHEN jordbruk = 25 THEN s.daa ELSE 0 END), ta.daa), 1) AS ar50_beite_daa,
               round(least(sum(CASE WHEN arealtype = 20 THEN s.daa ELSE 0 END), ta.daa), 1) AS ar50_innmark_daa,
               round(least(sum(CASE WHEN arealtype = 30 THEN s.daa ELSE 0 END), ta.daa), 1) AS ar50_skog_daa,
               round(least(sum(CASE WHEN arealtype = 60 THEN s.daa ELSE 0 END), ta.daa), 1) AS ar50_myr_daa
        FROM snitt s JOIN (SELECT teig_id, ST_Area(geom) / 1000.0 AS daa FROM teiger) ta USING(teig_id)
        GROUP BY s.teig_id, ta.daa
    """, [kommunenr])
    n = dict(ar50_flater=len(df), jordbruk_flater=int((df.arealtype == 20).sum()),
             teiger=con.execute("SELECT count(*) FROM teig_ar50").fetchone()[0],
             teiger_med_innmark=con.execute("SELECT count(*) FROM teig_ar50 WHERE ar50_innmark_daa >= ?", [cfg["kriterier"]["innmark_min_daa"]]).fetchone()[0],
             sek=round(time.time() - t0, 1))
    print("Steg 4a AR50:", n)
    con.close()
    return n


# ---------------------------------------------------------------- AR5 rundt tunet
def ar5_ved_punkt(x: float, y: float, px_m: float = 2.0, px: int = 50) -> list[dict]:
    """AR5-flater som treffer punktet (GetFeatureInfo, ~3 px toleranse). Svaret (msGMLOutput) har kun
    attributter og gml:Box, ingen polygon."""
    halv = px * px_m / 2
    params = dict(SERVICE="WMS", VERSION="1.3.0", REQUEST="GetFeatureInfo", LAYERS="AR5flater",
                  QUERY_LAYERS="AR5flater", CRS="EPSG:25833",
                  BBOX=f"{x-halv:.1f},{y-halv:.1f},{x+halv:.1f},{y+halv:.1f}",
                  WIDTH=px, HEIGHT=px, I=px // 2, J=px // 2,
                  INFO_FORMAT="application/vnd.ogc.gml", FEATURE_COUNT=10)
    for forsok in range(6):  # NIBIO bryter av og til forbindelsen eller svarer 503; vent og prøv igjen
        try:
            r = _ses.get(AR5_WMS, params=params, timeout=90)
            if r.status_code < 500:
                break
        except requests.RequestException as e:
            log.warning("AR5 WMS: %s (forsøk %d)", e, forsok + 1)
            if forsok == 5:
                raise
        time.sleep(5 * 2 ** forsok)
    r.raise_for_status()
    ut = []
    try:
        root = etree.fromstring(r.content)
    except etree.XMLSyntaxError:
        return ut
    for f in root.iter():
        if _local(f.tag) != "AR5flater_feature":
            continue
        d = {_local(c.tag): (c.text or "").strip() for c in f if len(c) == 0}
        ut.append(dict(sl_sdeid=d.get("sl_sdeid"), artype=int(d.get("artype") or 0), areal_da=float(d.get("areal_da") or 0),
                       artreslag=d.get("artreslag"), arskogbon=d.get("arskogbon"), argrunnf=d.get("argrunnf"),
                       verifisert=d.get("verifiseringsdato")))
    return ut


def steg4_ar5_tun(kommunenr: str, cfg: dict | None = None, radius_m: float = 45.0, n_pkt: int = 6, pause: float = 0.1) -> dict:
    """For hver kandidat: AR5-flater i tunpunktet og n_pkt punkter på radius_m (< 50 m-regelen).
    Gir ar5_tun_type, innmark_naer_tun og totalareal (daa) for innmarksflatene som berører tunsonen."""
    import json

    cfg = cfg or C.load()
    t0 = time.time()
    con = connect(C.db_path(cfg))
    rader = con.execute("SELECT bygningid, x, y FROM kandidat_v1 WHERE kommunenr=?", [kommunenr]).fetchall()
    con.close()  # hold ikke DB-låsen under lange nettverksløkker
    cache_f = C.derived_dir(cfg, kommunenr) / "ar5_tun_cache.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    az = np.deg2rad(np.arange(n_pkt) * 360 / n_pkt)
    offs = [(0.0, 0.0)] + list(zip(radius_m * np.sin(az), radius_m * np.cos(az)))

    def _slaa_opp(row):
        bid, x, y = row
        flater, tun_type = {}, None
        for k, (dx, dy) in enumerate(offs):
            for f in ar5_ved_punkt(x + dx, y + dy):
                if k == 0 and tun_type is None:
                    tun_type = f["artype"]
                if f["sl_sdeid"]:
                    flater.setdefault(f["sl_sdeid"], f)
            time.sleep(pause)
        return str(bid), dict(tun_type=tun_type, flater=list(flater.values()))

    from concurrent.futures import ThreadPoolExecutor

    mangler = [r for r in rader if str(r[0]) not in cache]
    with ThreadPoolExecutor(max_workers=TRAADER) as ex:
        for i, (key, c) in enumerate(ex.map(_slaa_opp, mangler), 1):
            cache[key] = c
            if i % 50 == 0:
                cache_f.write_text(json.dumps(cache))
                log.info("AR5 tun %d/%d (%.0f s)", i, len(mangler), time.time() - t0)
    ut = []
    for bid, x, y in rader:
        c = cache[str(bid)]
        innmark = [f for f in c["flater"] if f["artype"] in AR5_INNMARK]
        daa = {kode: round(sum(f["areal_da"] for f in innmark if f["artype"] == kode), 1) for kode in AR5_INNMARK}
        ut.append(dict(bygningid=bid, ar5_tun_type=c["tun_type"], innmark_naer_tun=len(innmark) > 0,
                       ar5_naer_fulldyrka_daa=daa[21], ar5_naer_overflatedyrka_daa=daa[22], ar5_naer_beite_daa=daa[23],
                       ar5_naer_innmark_daa=round(sum(daa.values()), 1), ar5_naer_antall_flater=len(innmark)))
    cache_f.write_text(json.dumps(cache))
    df = pd.DataFrame(ut)
    con = connect(C.db_path(cfg))
    con.register("_j", df)
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='jord_tun'").fetchone()[0]:
        con.execute("DELETE FROM jord_tun WHERE bygningid IN (SELECT bygningid FROM _j)")
        con.execute("INSERT INTO jord_tun SELECT * FROM _j")
    else:
        con.execute("CREATE TABLE jord_tun AS SELECT * FROM _j")
    con.unregister("_j")
    lag_views(con)
    n = dict(kandidater=len(rader), innmark_naer_tun=int(df.innmark_naer_tun.sum()), sek=round(time.time() - t0))
    print("Steg 4b AR5 tun:", n)
    print(con.execute("SELECT ar5_tun_type, count(*) FROM jord_tun GROUP BY 1 ORDER BY 2 DESC").fetchall())
    con.close()
    return n




if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    knr = next((a for a in sys.argv[1:] if a.isdigit()), "3336")
    if "ar5" in sys.argv:
        steg4_ar5_tun(knr)
    else:
        steg4_ar50(knr)
