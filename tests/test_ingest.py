"""Tester mot Rollag-data i data/raw/3336 (hoppes over hvis data mangler)."""
from pathlib import Path

import pytest

from odehus import ingest

RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "3336"
BYGG = RAW / "Basisdata_3336_Rollag_25833_MatrikkelenBygning_GML.gml"
TEIG = RAW / "Basisdata_3336_Rollag_25833_MatrikkelenEiendomskartTeig_GML.gml"
ADR = RAW / "Basisdata_3336_Rollag_25833_MatrikkelenAdresse_GML.gml"

pytestmark = pytest.mark.skipif(not BYGG.exists(), reason="Rollag-data ikke lastet ned")


def test_bygning_parses_all_features():
    df = ingest.les_bygning(BYGG)
    assert len(df) == 7118  # grep '<app:Bygning gml:id' gir 7118
    assert df.bygningid.is_unique
    assert df.x.between(165_000, 190_000).all() and df.y.between(6_652_000, 6_683_000).all()
    assert (df.kommunenr == "3336").all()
    assert set(df.status.unique()) <= {"TB", "FA", "FS", "GR", "IG", "IP", "MB", "MF", "MT", "RA"}
    assert (df.bygningstype == 113).sum() == 384
    assert df.sefrak.sum() == 1459  # harSefrakminne=true; 1519 sefrakIdent-elementer fordi noen bygg har flere


def test_teig_polygons_valid():
    teig, tm = ingest.les_teig(TEIG)
    assert len(teig) == 5153
    assert teig.teig_id.is_unique
    assert len(tm) >= len(teig)
    assert teig.areal_m2.gt(0).all()
    from shapely import wkb
    g = [wkb.loads(b) for b in teig.geom_wkb.head(200)]
    assert all(x.is_valid for x in g)


def test_adresse_parses():
    df = ingest.les_adresse(ADR)
    assert len(df) > 1000
    assert df.adresse_id.is_unique
    assert set(df.adressetype.unique()) <= {"Vegadresse", "Matrikkeladresse"}


def test_hoyde_api_batch(tmp_path):
    from odehus import config as C
    from odehus.download import hoyde_punkter
    cfg = C.load(); cfg["paths"]["derived"] = str(tmp_path)
    pts = [(173167.3, 6669851.6), (181370.7, 6667622.8)]
    h = hoyde_punkter(cfg, "3336", pts)
    assert 400 < h[pts[0]]["z"] < 500 and 180 < h[pts[1]]["z"] < 250
    h2 = hoyde_punkter(cfg, "3336", pts)  # fra cache
    assert h2 == h


def test_kandidat_v1():
    import duckdb
    from odehus import config as C
    db = C.db_path(C.load())
    if not db.exists():
        pytest.skip("ingen database")
    con = duckdb.connect(str(db), read_only=True); con.execute("LOAD spatial")
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='kandidat_v1'").fetchone()[0]:
        pytest.skip("kandidat_v1 ikke laget")
    n, nt, nm = con.execute("SELECT count(*), count(teig_geom), max(moh) FROM kandidat_v1 WHERE kommunenr='3336'").fetchone()
    assert n > 500 and nt == n and nm <= 700
    assert con.execute("SELECT count(*) FROM kandidat_v1 WHERE status IN ('RA','IG')").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM kandidat_v1 WHERE ST_Area(teig_geom) <= 0").fetchone()[0] == 0
