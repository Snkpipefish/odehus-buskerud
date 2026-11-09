"""Tester for jord, tilkomst, nDSM-proxy, score og eksport (DB-baserte hoppes over hvis tabeller mangler)."""
from pathlib import Path

import numpy as np
import pytest

from odehus import config as C

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def con():
    import duckdb
    db = C.db_path(C.load())
    if not db.exists():
        pytest.skip("ingen database")
    c = duckdb.connect(str(db), read_only=True)
    c.execute("LOAD spatial")
    yield c
    c.close()


def _har(con, tabell):
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [tabell]).fetchone()[0] > 0


def test_ar50_innmark_rimelig(con):
    if not _har(con, "teig_ar50"):
        pytest.skip("teig_ar50 mangler")
    n, neg, over = con.execute("""SELECT count(*), sum((ar50_innmark_daa < 0)::int),
        sum((a.ar50_innmark_daa > ST_Area(t.geom)/1000.0 * 1.05 + 0.1)::int) FROM teig_ar50 a JOIN teig t USING(teig_id)""").fetchone()
    assert n > 100 and neg == 0 and over == 0  # innmark kan ikke overstige teigarealet


def test_tilkomst(con):
    if not _har(con, "tilkomst"):
        pytest.skip("tilkomst mangler")
    r = con.execute("SELECT count(*), sum((veg_m IS NULL)::int), min(veg_m), max(naboer_200m), sum((veg_kategori IN ('P','S')) = flagg_privat_veg) FROM tilkomst").fetchone()
    assert r[0] > 500 and r[1] == 0 and r[2] >= 0 and r[4] == r[0]
    # Haugerud 24/1 ligger ved veg (<100 m) iflg. kart
    d = con.execute("SELECT veg_m FROM tilkomst t JOIN bygg b USING(bygningid) WHERE b.gnr=24 AND b.bnr=1 AND b.type=113").fetchone()
    assert d and d[0] < 100


def test_ndsm_indikatorer_syntetisk():
    from odehus.imagery import ndsm_indikatorer, HALV
    n = np.zeros((200, 200), dtype="float32")
    yy, xx = np.mgrid[:200, :200]
    r = np.hypot(yy - 100, xx - 100)
    n[r <= 6] = 7.0          # hus, 7 m
    n[(r > 12) & (r <= 40) & (xx > 100)] = 12.0   # halve ringen er skog (fra 12 m pga. halvpiksel-forskyvning)
    n[np.hypot(yy - 100, xx - 160) <= 5] = 8.0   # driftsbygning 60 m øst
    x, y = 1000.0, 2000.0
    ind = ndsm_indikatorer(n, x, y, andre_bygg=[(x + 60, y)])
    assert ind["bygg_hoyde_m"] == 7.0 and 45 <= ind["gjengroing_tun_pct"] <= 55 and ind["forfall_score"] == 1
    n[r <= 6] = 0.5
    assert ndsm_indikatorer(n, x, y, [])["forfall_score"] == 3


def test_score_og_eksport(con):
    if not _har(con, "score"):
        pytest.skip("score mangler")
    n, nr, mx, mn = con.execute("SELECT count(*), count(DISTINCT rank), max(total), min(total) FROM score").fetchone()
    assert n == nr and 0 <= mn <= mx <= 1
    csv = ROOT / "out" / "3336_shortlist.csv"
    if csv.exists():
        import pandas as pd
        df = pd.read_csv(csv)
        assert len(df) == con.execute("SELECT count(*) FROM score WHERE kommunenr='3336'").fetchone()[0]
        assert df["rank"].is_monotonic_increasing and df.lenke_seeiendom.str.startswith("https://seeiendom").all()
