"""Terreng: DTM fra Kartverkets WCS «Nasjonal høydemodell DTM 25833», slope/aspect på tunet og
egen horisontprofil.

Verifisert 2026-11-07:
- WCS 2.0.1-syntaks avvises (ArcGIS Server, HTTP 400). WCS 1.0.0 med BBOX/WIDTH/HEIGHT virker:
  https://wcs.geonorge.no/skwms1/wcs.hoyde-dtm-nhm-25833?service=WCS&version=1.0.0&request=GetCoverage
    &coverage=nhm_dtm_topo_25833&crs=EPSG:25833&format=GeoTIFF&bbox=...&width=2000&height=2000
- 20 km × 20 km på 10 m (2000 px) tar ~2 s. 40 km gir 504. Vi fliser derfor i 20 km.
- Verdi ved testpunkt avvek 0,25 m fra høyde-API-et (DTM1), så resampling er fornuftig.
"""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.merge import merge

from .config import derived_dir, raw_dir
from .download import _session

log = logging.getLogger(__name__)

WCS = "https://wcs.geonorge.no/skwms1/wcs.hoyde-dtm-nhm-25833"
COVERAGE = "nhm_dtm_topo_25833"
TILE_M = 20_000
RES_M = 10
R_JORD = 6_371_000.0


def _hent_flis(sti: Path, x0: float, y0: float, res: int = RES_M) -> Path:
    if sti.exists() and sti.stat().st_size > 1000:
        return sti
    px = TILE_M // res
    params = dict(
        service="WCS", version="1.0.0", request="GetCoverage", coverage=COVERAGE,
        crs="EPSG:25833", format="GeoTIFF",
        bbox=f"{x0:.0f},{y0:.0f},{x0 + TILE_M:.0f},{y0 + TILE_M:.0f}", width=px, height=px,
    )
    for forsok in range(6):  # WCS gir av og til 504 på 20 km-fliser; vent og prøv igjen
        try:
            r = _session.get(WCS, params=params, timeout=300)
            if r.status_code < 500:
                break
        except requests.RequestException as e:
            log.warning("WCS DTM: %s (forsøk %d)", e, forsok + 1)
            if forsok == 5:
                raise
        time.sleep(10 * 2 ** forsok)
    r.raise_for_status()
    if "tiff" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"WCS ga {r.headers.get('content-type')}: {r.text[:300]}")
    sti.write_bytes(r.content)
    log.info("DTM-flis %s (%d kB)", sti.name, len(r.content) // 1024)
    return sti


def hent_dtm(cfg: dict, kommunenr: str, bbox: tuple[float, float, float, float],
             buffer_m: float = 15_000, res: int = RES_M) -> Path:
    """Laster ned (cachet) DTM i `res` m oppløsning som dekker bbox + buffer, og slår sammen
    flisene til data/derived/<knr>/dtm<res>.tif."""
    x0, y0, x1, y1 = bbox
    xs = range(int(math.floor((x0 - buffer_m) / TILE_M) * TILE_M), int(x1 + buffer_m), TILE_M)
    ys = range(int(math.floor((y0 - buffer_m) / TILE_M) * TILE_M), int(y1 + buffer_m), TILE_M)
    flisdir = raw_dir(cfg, kommunenr) / f"dtm{res}"
    flisdir.mkdir(exist_ok=True)
    fliser = [_hent_flis(flisdir / f"tile_{x}_{y}.tif", x, y, res) for x in xs for y in ys]
    ut = derived_dir(cfg, kommunenr) / f"dtm{res}.tif"
    if ut.exists() and ut.stat().st_mtime >= max(f.stat().st_mtime for f in fliser):
        return ut
    srcs = [rasterio.open(f) for f in fliser]
    arr, tr = merge(srcs)
    meta = srcs[0].meta.copy()
    meta.update(height=arr.shape[1], width=arr.shape[2], transform=tr, compress="deflate", nodata=-9999.0)
    arr = np.where(np.isfinite(arr), arr, -9999.0).astype("float32")
    with rasterio.open(ut, "w", **meta) as dst:
        dst.write(arr)
    for s in srcs:
        s.close()
    log.info("DTM slått sammen: %s %sx%s px", ut.name, arr.shape[2], arr.shape[1])
    return ut


class Terreng:
    """Holder DTM-rasteret i minnet og svarer på punktspørringer."""

    def __init__(self, dtm: Path):
        with rasterio.open(dtm) as d:
            self.arr = d.read(1).astype("float64")
            self.tr = d.transform
            self.res = d.res[0]
            self.nodata = d.nodata
        self.arr[self.arr == self.nodata] = np.nan
        self.x0, self.y0 = self.tr.c, self.tr.f  # øvre venstre hjørne

    def _rc(self, x, y):
        col = np.floor((np.asarray(x) - self.x0) / self.res).astype(int)
        row = np.floor((self.y0 - np.asarray(y)) / self.res).astype(int)
        return row, col

    def hoyde(self, x: float, y: float) -> float:
        r, c = self._rc(x, y)
        return float(self.arr[r, c])

    def slope_aspect(self, x: float, y: float, vindu_m: float = 30) -> tuple[float, float | None]:
        """Horns metode på et (vindu_m/res)-cellers nabolag rundt punktet (30 m => 3×3 på 10 m).
        Returnerer (helning i grader, aspect i grader med klokka fra nord = retningen bakken heller NED mot).
        Aspect er None når helningen er < 0,5°."""
        h = max(1, int(round(vindu_m / self.res / 2)))
        r, c = self._rc(x, y)
        w = self.arr[r - h : r + h + 1, c - h : c + h + 1]
        if w.shape != (2 * h + 1, 2 * h + 1) or np.isnan(w).any():
            return float("nan"), None
        # Vektet gradient (Horn) generalisert: differanse av kolonne-/radmiddel over avstanden 2*h*res
        east = w[:, -1].mean() - w[:, 0].mean()
        north = w[0, :].mean() - w[-1, :].mean()
        dist = 2 * h * self.res
        dzdx, dzdy = east / dist, north / dist
        slope = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
        if slope < 0.5:
            return slope, None
        aspect = math.degrees(math.atan2(-dzdx, -dzdy)) % 360  # nedoverretning, 0 = N, 90 = Ø
        return slope, aspect

    def horisont(self, x: float, y: float, n_retn: int = 16, maks_m: float = 15_000,
                 obs_h: float = 2.0) -> np.ndarray:
        """Høyeste terrengvinkel (grader over horisontalplanet) i n_retn retninger, 0 = nord, med
        klokka. Tettere sampling nær punktet. Jordkrumning og refraksjon (k=0.13) trekkes fra."""
        d = np.concatenate([np.arange(self.res, 500, self.res), np.arange(500, 3000, 30), np.arange(3000, maks_m + 1, 100)])
        az = np.deg2rad(np.arange(n_retn) * 360.0 / n_retn)
        px = x + np.outer(np.sin(az), d)
        py = y + np.outer(np.cos(az), d)
        r, c = self._rc(px, py)
        ok = (r >= 0) & (r < self.arr.shape[0]) & (c >= 0) & (c < self.arr.shape[1])
        z = np.full(r.shape, np.nan)
        z[ok] = self.arr[r[ok], c[ok]]
        z0 = self.hoyde(x, y) + obs_h
        krum = (d ** 2) / (2 * R_JORD) * (1 - 0.13)
        ang = np.degrees(np.arctan2(z - z0 - krum, d))
        ang = np.where(np.isnan(ang), -90, ang)
        return np.clip(ang.max(axis=1), 0, None)


# ---------------------------------------------------------------- Steg 3a: terreng for kandidater
def steg3_terreng(kommunenr: str, cfg: dict | None = None) -> dict:
    import time

    import pandas as pd

    from . import config as C
    from .ingest import connect

    cfg = cfg or C.load()
    t0 = time.time()
    con = connect(C.db_path(cfg))
    pts = con.execute("SELECT bygningid, x, y, moh FROM kandidat_v1 WHERE kommunenr=?", [kommunenr]).fetchall()
    xs, ys = [p[1] for p in pts], [p[2] for p in pts]
    dtm = hent_dtm(cfg, kommunenr, (min(xs), min(ys), max(xs), max(ys)))
    T = Terreng(dtm)
    rows = []
    for bid, x, y, moh in pts:
        slope, aspect = T.slope_aspect(x, y, 30)
        hz = T.horisont(x, y)
        rows.append(dict(bygningid=bid, moh_dtm=T.hoyde(x, y), slope_deg=slope, aspect_deg=aspect,
                         horisont_egen=[round(float(v), 2) for v in hz],
                         horisont_maks=float(hz.max()), horisont_sor=float(hz[6:11].mean())))  # 135–225°
    df = pd.DataFrame(rows)
    con.register("_t", df)
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='terreng'").fetchone()[0]:
        con.execute("DELETE FROM terreng WHERE bygningid IN (SELECT bygningid FROM _t)")
        con.execute("INSERT INTO terreng SELECT * FROM _t")
    else:
        con.execute("CREATE TABLE terreng AS SELECT * FROM _t")
    con.unregister("_t")
    n = dict(kandidater=len(pts), dtm=str(dtm.name), sek=round(time.time() - t0, 1))
    print("Steg 3a terreng:", n)
    print(con.execute("""SELECT round(avg(slope_deg),1) AS slope_snitt, round(avg(horisont_maks),1) AS hz_maks_snitt,
                            round(avg(horisont_sor),1) AS hz_sor_snitt, count(aspect_deg) AS med_aspect,
                            sum((aspect_deg BETWEEN 135 AND 225)::int) AS so_sv,
                            round(avg(abs(moh_dtm - k.moh)),2) AS moh_avvik_snitt
                         FROM terreng t JOIN kandidat_v1 k USING(bygningid) WHERE k.kommunenr=?""", [kommunenr]).df().to_string(index=False))
    con.close()
    return n


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    steg3_terreng(sys.argv[1] if len(sys.argv) > 1 else "3336")
