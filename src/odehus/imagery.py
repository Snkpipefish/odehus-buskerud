"""Steg 6: tilstandsindikatorer per kandidat.

Ortofoto (Norge i bilder) er Norge digitalt-begrenset i alle kanaler (WMS, WMTS, prosjekter) og krever
BAAT-billett – verifisert 2026-11-07. Inntil tilgang er avklart brukes en ÅPEN proxy:
  nDSM = DOM − DTM fra Kartverkets WCS (nasjonal høydemodell, 1 m) i et 200 × 200 m vindu rundt bygget.
  - bygg_hoyde_m: maks nDSM innen 10 m av bygningspunktet. Under ~2 m = ingen stående bygning.
  - gjengroing_tun_pct: andel celler med nDSM > 2 m i ringen 10–40 m rundt bygget, der sirkler på 12 m
    rundt alle andre registrerte bygg er maskert ut (så driftsbygninger ikke telles som skog).
  - gjengroing_naer_pct: samme for ringen 40–100 m.
  forfall_score (proxy, 0–3): 3 = ingen stående bygning, 2 = tun > 50 % gjengrodd, 1 = 25–50 %, 0 = < 25 %.
Laserdataene har én epoke (NHM, 2016–2022 avhengig av prosjekt) – ingen endringsanalyse.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests

from . import config as C
from .download import _session
from .ingest import connect
from .views import lag_views

log = logging.getLogger(__name__)
WCS = "https://wcs.geonorge.no/skwms1/wcs.hoyde-{m}-nhm-25833"
COV = {"dom": "nhm_dom_topo_25833", "dtm": "nhm_dtm_topo_25833"}
HALV = 100  # m
TRAADER = 4
RES = 1


def _hent(modell: str, sti: Path, x: float, y: float) -> np.ndarray:
    """Henter en 200x200 m flis fra WCS. Flisen lagres ikke på disk (59 000 fliser fylte disken 2026-11-09);
    en allerede nedlastet flis brukes hvis den finnes."""
    from rasterio.io import MemoryFile

    if sti.exists():
        with rasterio.open(sti) as d:
            return d.read(1).astype("float32")
    px = 2 * HALV // RES
    params = dict(service="WCS", version="1.0.0", request="GetCoverage", coverage=COV[modell], crs="EPSG:25833",
                  format="GeoTIFF", width=px, height=px, bbox=f"{x-HALV:.0f},{y-HALV:.0f},{x+HALV:.0f},{y+HALV:.0f}")
    siste = ""
    for forsok in range(5):  # WCS gir av og til 504 eller en ServiceException; vent og prøv igjen
        try:
            r = _session.get(WCS.format(m=modell), params=params, timeout=120)
        except requests.RequestException as e:
            siste = str(e)
            log.warning("WCS %s: %s (forsøk %d)", modell, e, forsok + 1)
        else:
            if r.status_code == 200 and "tiff" in r.headers.get("content-type", ""):
                with MemoryFile(r.content) as mf, mf.open() as d:
                    return d.read(1).astype("float32")
            siste = f"{r.status_code}: {r.text[:200]}".replace("\n", " ")
            if 400 <= r.status_code < 500:
                break
            log.warning("WCS %s ga %s (forsøk %d)", modell, siste[:120], forsok + 1)
        time.sleep(5 * 2 ** forsok)
    raise RuntimeError(f"WCS {modell}: {siste}")


def ndsm_indikatorer(n: np.ndarray, x: float, y: float, andre_bygg: list[tuple[float, float]]) -> dict:
    h, w = n.shape
    yy, xx = np.mgrid[:h, :w]
    ex = x - HALV + (xx + 0.5) * RES          # cellesentre i kartkoordinater
    ny = y + HALV - (yy + 0.5) * RES
    r = np.hypot(ex - x, ny - y)
    maske = np.ones_like(n, dtype=bool)
    for bx, by in andre_bygg:
        maske &= np.hypot(ex - bx, ny - by) > 12
    hoy = n > 2.0
    tun = (r > 10) & (r <= 40) & maske
    naer = (r > 40) & (r <= 100) & maske
    bygg_h = float(np.nanmax(n[r <= 10])) if (r <= 10).any() else float("nan")
    g_tun = float(100 * hoy[tun].mean()) if tun.any() else float("nan")
    g_naer = float(100 * hoy[naer].mean()) if naer.any() else float("nan")
    if np.isnan(bygg_h) or bygg_h < 2.0:
        score, grunn = 3, f"ingen stående bygning i laserdata (maks {bygg_h:.1f} m innen 10 m)"
    elif g_tun > 50:
        score, grunn = 2, f"tunet {g_tun:.0f} % dekket av vegetasjon > 2 m (10–40 m)"
    elif g_tun > 25:
        score, grunn = 1, f"delvis gjengrodd tun, {g_tun:.0f} % > 2 m"
    else:
        score, grunn = 0, f"åpent tun ({g_tun:.0f} % > 2 m), bygg {bygg_h:.1f} m"
    return dict(bygg_hoyde_m=round(bygg_h, 1), gjengroing_tun_pct=round(g_tun, 1), gjengroing_naer_pct=round(g_naer, 1),
                forfall_score=score, forfall_begrunnelse=grunn)


def steg6_ndsm(kommunenr: str, cfg: dict | None = None, pause: float = 0.1) -> dict:
    cfg = cfg or C.load()
    t0 = time.time()
    con = connect(C.db_path(cfg))
    rader = con.execute("SELECT bygningid, x, y FROM kandidat_v1 WHERE kommunenr=? ORDER BY bygningid", [kommunenr]).fetchall()
    alle = con.execute("SELECT x, y FROM bygg WHERE kommunenr=?", [kommunenr]).fetchall()
    con.close()
    alle = np.array(alle)
    d = C.raw_dir(cfg, kommunenr) / "ndsm"
    d.mkdir(exist_ok=True)
    def _en(row):
        bid, x, y = row
        try:
            dom = _hent("dom", d / f"{bid}_dom.tif", x, y)
            dtm = _hent("dtm", d / f"{bid}_dtm.tif", x, y)
        except Exception as e:  # noqa: BLE001 - én feilet flis skal ikke velte hele kommunen
            log.error("nDSM %s: %s", bid, str(e)[:200].replace("\n", " "))
            return dict(bygningid=bid, bygg_hoyde_m=float("nan"), gjengroing_tun_pct=float("nan"), gjengroing_naer_pct=float("nan"),
                        forfall_score=float("nan"), forfall_begrunnelse="laserdata ikke tilgjengelig", forfall_kilde="ndsm_mangler",
                        img_old="", img_new="", img_old_aar="", img_new_aar="")
        n = dom - dtm
        n[(dom < -1000) | (dtm < -1000)] = np.nan
        naer = alle[(np.abs(alle[:, 0] - x) < HALV + 15) & (np.abs(alle[:, 1] - y) < HALV + 15)]
        andre = [(bx, by) for bx, by in naer if np.hypot(bx - x, by - y) > 0.5]
        time.sleep(pause)
        return dict(bygningid=bid, **ndsm_indikatorer(n, x, y, andre), forfall_kilde="ndsm_proxy",
                    img_old="", img_new="", img_old_aar="", img_new_aar="")

    from concurrent.futures import ThreadPoolExecutor

    ut = []
    with ThreadPoolExecutor(max_workers=TRAADER) as ex:
        for i, res in enumerate(ex.map(_en, rader), 1):
            ut.append(res)
            if i % 100 == 0:
                log.info("nDSM %d/%d (%.0f s)", i, len(rader), time.time() - t0)
    df = pd.DataFrame(ut)
    con = connect(C.db_path(cfg))
    con.register("_f", df)
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='forfall'").fetchone()[0]:
        con.execute("DELETE FROM forfall WHERE bygningid IN (SELECT bygningid FROM _f)")
        kol = ", ".join(df.columns)
        con.execute(f"INSERT INTO forfall ({kol}) SELECT {kol} FROM _f")  # tabellen kan ha ekstra kolonner (visuell vurdering)
    else:
        con.execute("CREATE TABLE forfall AS SELECT * FROM _f")
    con.unregister("_f")
    lag_views(con)
    print("Steg 6 nDSM:", dict(kandidater=len(df), sek=round(time.time() - t0)))
    print(con.execute("SELECT forfall_score, count(*), round(avg(bygg_hoyde_m),1) h, round(avg(gjengroing_tun_pct)) g FROM forfall GROUP BY 1 ORDER BY 1").fetchall())
    con.close()
    return dict(kandidater=len(df))


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    steg6_ndsm(sys.argv[1] if len(sys.argv) > 1 else "3336")
