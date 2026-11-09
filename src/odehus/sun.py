"""Sol: PVGIS (horisont + innstråling) og pvlib (soltimer over horisont).

PVGIS v5.2 (verifisert 2026-11-07, gratis, ingen nøkkel):
- printhorizon: 48 retninger à 7,5°. Azimut A i PVGIS-konvensjon (0 = sør, øst negativ, ±180 = nord).
  Vi regner om til 0 = nord med klokka: az = (A + 180) mod 360.
- MRcalc horirrad=1: månedlig global innstråling på horisontal flate H(h)_m [kWh/m²], SARAH2 2005–2020.
  `userhorizon` = høyde i grader i like fordelte retninger fra nord med klokka.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pvlib

from .config import derived_dir
import requests

log = logging.getLogger(__name__)
PVGIS = "https://re.jrc.ec.europa.eu/api/v5_2"
PVGIS_PAUSE = 0.1   # per tråd
TRAADER = 4
PVGIS_AAR = (2016, 2020)
DATOER = {"mars": date(2024, 3, 1), "mai": date(2024, 5, 1), "juli": date(2024, 7, 1), "sept": date(2024, 9, 1)}
N_RETN = 16

_sist = [0.0]
_lås = __import__('threading').Lock()
SOL_PCT_SQL = """UPDATE sol SET sol_pct = p.pct FROM (
    SELECT bygningid, round(50 * percent_rank() OVER (ORDER BY innstraling_apr_sep)
                         + 50 * percent_rank() OVER (ORDER BY soltimer_mars), 1) AS pct FROM sol
) p WHERE sol.bygningid = p.bygningid"""
# Egen sesjon med requests' standard User-Agent: PVGIS' brannmur avviste vår egendefinerte UA-streng.
_pv = requests.Session()


def _pvgis(cfg: dict, kommunenr: str, endpoint: str, params: dict) -> dict:
    """GET mot PVGIS med diskcache i data/derived/<knr>/pvgis/ og enkel throttling/retry."""
    d = derived_dir(cfg, kommunenr) / "pvgis"
    d.mkdir(exist_ok=True)
    nokkel = hashlib.sha1(json.dumps([endpoint, params], sort_keys=True).encode()).hexdigest()[:16]
    f = d / f"{endpoint}_{nokkel}.json"
    if f.exists():
        return json.loads(f.read_text())
    for forsok in range(5):
        with _lås:
            vent = PVGIS_PAUSE - (time.time() - _sist[0])
            if vent > 0:
                time.sleep(vent)
            _sist[0] = time.time()
        try:
            r = _pv.get(f"{PVGIS}/{endpoint}", params={**params, "outputformat": "json"}, timeout=90)
        except requests.RequestException as e:  # nettverksfeil: vent og prøv igjen
            log.warning("PVGIS %s: %s (forsøk %d)", endpoint, e, forsok + 1)
            time.sleep(10 * 2 ** forsok)
            continue
        if r.status_code == 200:
            f.write_text(r.text)
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** forsok)
            continue
        raise RuntimeError(f"PVGIS {endpoint} {r.status_code}: {r.text[:200]}")
    raise RuntimeError(f"PVGIS {endpoint}: ga opp etter 5 forsøk")


def pvgis_horisont(cfg: dict, kommunenr: str, lat: float, lon: float) -> np.ndarray:
    """Horisonthøyde i N_RETN retninger fra nord med klokka (plukker PVGIS' 7,5°-verdier)."""
    d = _pvgis(cfg, kommunenr, "printhorizon", dict(lat=round(lat, 5), lon=round(lon, 5)))
    prof = {round((p["A"] + 180) % 360, 1): p["H_hor"] for p in d["outputs"]["horizon_profile"]}
    az = np.arange(N_RETN) * 360 / N_RETN
    return np.array([prof.get(round(a, 1), np.nan) for a in az])


def pvgis_innstraling(cfg: dict, kommunenr: str, lat: float, lon: float,
                      horisont: np.ndarray | None = None) -> dict:
    """Gj.sn. global innstråling på horisontal flate [kWh/m²] per år for apr–sep og hele året."""
    p = dict(lat=round(lat, 5), lon=round(lon, 5), horirrad=1, startyear=PVGIS_AAR[0], endyear=PVGIS_AAR[1])
    if horisont is not None:
        p["userhorizon"] = ",".join(f"{v:.1f}" for v in horisont)
    d = _pvgis(cfg, kommunenr, "MRcalc", p)
    m = pd.DataFrame(d["outputs"]["monthly"])
    aar = m.year.nunique()
    return dict(
        innstraling_apr_sep=round(float(m[m.month.between(4, 9)]["H(h)_m"].sum() / aar), 1),
        innstraling_aar=round(float(m["H(h)_m"].sum() / aar), 1),
        pvgis_horisont_brukt=d["inputs"]["meteo_data"].get("horizon_data"),
    )


def soltimer(lat: float, lon: float, horisont: np.ndarray, dag: date, steg_min: int = 2) -> float:
    """Timer sola står over terrenghorisonten den gitte dagen (lineær interpolasjon mellom retningene)."""
    t = pd.date_range(f"{dag}T00:00", f"{dag}T23:59", freq=f"{steg_min}min", tz="Europe/Oslo")
    sp = pvlib.solarposition.get_solarposition(t, lat, lon)
    az = np.append(np.arange(N_RETN) * 360 / N_RETN, 360.0)
    hz = np.append(horisont, horisont[0])
    terskel = np.interp(sp.azimuth.values, az, hz)
    over = sp.apparent_elevation.values > terskel
    return round(float(over.sum() * steg_min / 60), 2)


# ---------------------------------------------------------------- Steg 3b
def steg3_sol(kommunenr: str, cfg: dict | None = None, avvik_terskel: float = 2.0) -> dict:
    from pyproj import Transformer

    from . import config as C
    from .ingest import connect
    from .views import lag_views

    cfg = cfg or C.load()
    t0 = time.time()
    til_wgs = Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True)
    con = connect(C.db_path(cfg))
    rader = con.execute(
        "SELECT k.bygningid, k.x, k.y, t.horisont_egen FROM kandidat_v1 k JOIN terreng t USING(bygningid) WHERE k.kommunenr=?",
        [kommunenr],
    ).fetchall()
    con.close()  # hold ikke DB-låsen under lange nettverksløkker
    def _en(row):
        bid, x, y, hz_egen = row
        lon, lat = til_wgs.transform(x, y)
        hz_egen = np.array(hz_egen)
        try:
            hz_pv = pvgis_horisont(cfg, kommunenr, lat, lon)
            avvik = float(np.nanmax(np.abs(hz_egen - hz_pv)))
            bruk_egen = avvik > avvik_terskel
            hz = hz_egen if bruk_egen else hz_pv
            inn = pvgis_innstraling(cfg, kommunenr, lat, lon, hz)
        except RuntimeError as e:
            # PVGIS' landmaske (grov) avviser øyer og strandkant: «Location over the sea».
            # Bruk egen horisont og hent innstråling fra nærmeste landpunkt (PVGIS-ruten er uansett ~5 km).
            if "over the sea" not in str(e):
                raise
            hz_pv, avvik, bruk_egen, hz = np.full(N_RETN, np.nan), float("nan"), True, hz_egen
            inn = dict(innstraling_apr_sep=float("nan"), innstraling_aar=float("nan"), pvgis_horisont_brukt=None)
            for d in (0.01, 0.02, 0.04):
                for dy, dx in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                    try:
                        inn = pvgis_innstraling(cfg, kommunenr, lat + dy * d, lon + dx * 2 * d, hz)
                        break
                    except RuntimeError as e2:
                        if "over the sea" not in str(e2):
                            raise
                else:
                    continue
                break
        return dict(
            bygningid=bid, lat=round(lat, 6), lon=round(lon, 6),
            horisont_pvgis=[round(float(v), 1) for v in hz_pv],
            horisont_avvik_maks=round(avvik, 1), horisont_kilde="egen" if bruk_egen else "pvgis",
            **{f"soltimer_{k}": soltimer(lat, lon, hz, d) for k, d in DATOER.items()},
            **inn,
        )

    from concurrent.futures import ThreadPoolExecutor

    ut = []
    with ThreadPoolExecutor(max_workers=TRAADER) as ex:
        for i, res in enumerate(ex.map(_en, rader), 1):
            ut.append(res)
            if i % 100 == 0:
                log.info("sol %d/%d (%.0f s)", i, len(rader), time.time() - t0)
    df = pd.DataFrame(ut)
    con = connect(C.db_path(cfg))
    con.register("_s", df)
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='sol'").fetchone()[0]:
        con.execute("DELETE FROM sol WHERE bygningid IN (SELECT bygningid FROM _s)")
        kol = ", ".join(df.columns)
        con.execute(f"INSERT INTO sol ({kol}) SELECT {kol} FROM _s")  # sol_pct fylles under
    else:
        con.execute("CREATE TABLE sol AS SELECT * FROM _s")
    con.unregister("_s")
    # sol_pct: snitt av percentil for innstråling apr–sep (PVGIS, 5 km-ruter, sommertung) og percentil for
    # soltimer 1. mars (egen horisont, 10 m-terreng, skiller tun fra hverandre). Regnes over alle kandidater
    # i databasen = fylket når alle kommuner er lastet.
    con.execute("ALTER TABLE sol ADD COLUMN IF NOT EXISTS sol_pct DOUBLE")
    con.execute(SOL_PCT_SQL)
    lag_views(con)
    n = dict(kandidater=len(rader), sek=round(time.time() - t0))
    print("Steg 3b sol:", n)
    print(con.execute("""SELECT horisont_kilde, count(*) AS n, round(avg(horisont_avvik_maks),1) AS avvik_snitt,
                                round(avg(soltimer_mars),1) AS mars, round(avg(soltimer_mai),1) AS mai,
                                round(avg(soltimer_juli),1) AS juli, round(avg(soltimer_sept),1) AS sept,
                                round(min(innstraling_apr_sep)) AS inn_min, round(avg(innstraling_apr_sep)) AS inn_snitt,
                                round(max(innstraling_apr_sep)) AS inn_maks
                         FROM sol GROUP BY 1""").df().to_string(index=False))
    con.close()
    return n


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    steg3_sol(sys.argv[1] if len(sys.argv) > 1 else "3336")
