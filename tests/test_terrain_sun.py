"""Terreng- og soltester mot Rollag-DTM (hoppes over hvis DTM mangler)."""
from datetime import date
from pathlib import Path

import numpy as np
import pytest

DTM = Path(__file__).resolve().parents[1] / "data" / "derived" / "3336" / "dtm10.tif"
pytestmark = pytest.mark.skipif(not DTM.exists(), reason="dtm10.tif for Rollag mangler")


@pytest.fixture(scope="module")
def T():
    from odehus.terrain import Terreng
    return Terreng(DTM)


def test_hoyde_mot_hoyde_api(T):
    # høyde-API (DTM1) sa 444.19 og 212.54 for disse punktene
    assert abs(T.hoyde(173167.3, 6669851.6) - 444.19) < 2
    assert abs(T.hoyde(181370.7, 6667622.8) - 212.54) < 2


def test_slope_aspect_konvensjon(T):
    # Haugerud 24/1 heller ned mot sørøst (dalen ligger i øst)
    slope, aspect = T.slope_aspect(173167.3, 6669851.6)
    assert 5 < slope < 20 and 90 < aspect < 180


def test_horisont_form(T):
    hz = T.horisont(173167.3, 6669851.6)
    assert hz.shape == (16,) and (hz >= 0).all() and hz.max() < 45
    # terrenget stiger mot nordvest -> horisonten er høyest i NV-kvadranten
    assert hz[12:15].mean() > hz[2:6].mean()


def test_syntetisk_horisont_flat():
    """Flat DTM gir 0° horisont overalt, og en 100 m høy vegg 1 km mot sør gir ~5,6° i sør."""
    from odehus.terrain import Terreng
    import rasterio
    from rasterio.transform import from_origin
    arr = np.full((400, 400), 100.0, dtype="float32")
    arr[300:, :] = 200.0  # rader >= 300 (sør for y=1000) er 100 m høyere
    p = Path("/tmp") / "odehus_test_flat.tif"
    with rasterio.open(p, "w", driver="GTiff", height=400, width=400, count=1, dtype="float32",
                       crs="EPSG:25833", transform=from_origin(0, 4000, 10, 10), nodata=-9999.0) as d:
        d.write(arr, 1)
    T = Terreng(p)
    hz = T.horisont(2000, 2000)  # vegg starter 1000 m sør (y=1000)
    assert hz[0] == 0 and hz[4] == 0 and hz[12] == 0
    assert abs(hz[8] - np.degrees(np.arctan2(100 - 2, 1000))) < 0.3


def test_soltimer():
    from odehus.sun import soltimer
    lat, lon = 60.035, 9.129
    flat = np.zeros(16)
    juli, mars = soltimer(lat, lon, flat, date(2024, 7, 1)), soltimer(lat, lon, flat, date(2024, 3, 1))
    assert 17.5 < juli < 19.5 and 10 < mars < 11.5  # flat horisont: 18.6 / 10.4 t
    vegg = np.full(16, 20.0)
    assert soltimer(lat, lon, vegg, date(2024, 3, 1)) < mars - 2


def test_pvgis_azimut_konvensjon():
    from odehus.sun import pvgis_horisont
    from odehus import config as C
    cfg = C.load()
    hz = pvgis_horisont(cfg, "3336", 60.035152, 9.12906)
    assert hz.shape == (16,) and not np.isnan(hz).any()
    # PVGIS: A=-180 -> nord 0.8, A=90 -> vest 6.1 (verifisert 2026-11-07)
    assert hz[0] == pytest.approx(0.8) and hz[12] == pytest.approx(6.1)
