"""Steg 7a: scoring. total = w_sol*sol_pct/100 + w_innmark*min(innmark,tak)/tak + w_forfall*forfall/3 + w_aspect*aspectfaktor."""
from __future__ import annotations

from . import config as C
from .ingest import connect
from .views import lag_views


def steg7_score(kommunenr: str | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or C.load()
    w, kr = cfg["score"], cfg["kriterier"]
    a0, a1 = kr["aspect_foretrukket"]
    b0, b1 = kr["aspect_akseptabelt"]
    con = connect(C.db_path(cfg))
    lag_views(con)
    har_forfall = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='forfall'").fetchone()[0] > 0
    forfall = "coalesce(forfall_score, 0)" if har_forfall else "0"
    if har_forfall and con.execute("SELECT count(*) FROM information_schema.columns WHERE table_name='forfall' AND column_name='forfall_visuell'").fetchone()[0]:
        # Kalibrering: for rader som bare har laserproxy brukes gjennomsnittlig visuell score gitt proxy-verdien
        # (fasit fra Rollag). Visuelt vurderte rader beholder sin score.
        # Krymping mot proxyverdien ved få observasjoner (k=5), så én feil ikke nuller ut en hel klasse.
        kal = {int(k): (sum_v + 5 * k) / (n + 5) for k, sum_v, n in
               con.execute("SELECT forfall_proxy, sum(forfall_visuell), count(*) FROM forfall WHERE forfall_visuell IS NOT NULL GROUP BY 1").fetchall()}
        case = " ".join(f"WHEN {int(k)} THEN {v:.3f}" for k, v in sorted(kal.items()))
        forfall = f"(CASE WHEN forfall_kilde = 'visuell' THEN forfall_score ELSE CASE forfall_score {case} ELSE 0 END END)"
        print("forfall-kalibrering (proxy -> snitt visuell):", {int(k): round(v, 2) for k, v in sorted(kal.items())})
    con.execute(f"""
        CREATE OR REPLACE TABLE score AS
        WITH k AS (
            SELECT bygningid, kommunenr,
                   coalesce(sol_pct, 50) / 100.0 AS sol_f,
                   least(coalesce(innmark_daa, 0), {w['innmark_tak_daa']}) / {w['innmark_tak_daa']} AS innmark_f,
                   {forfall} / 3.0 AS forfall_f,
                   CASE WHEN aspect_deg BETWEEN {a0} AND {a1} THEN 1.0
                        WHEN aspect_deg BETWEEN {b0} AND {b1} THEN 0.5
                        WHEN aspect_deg IS NULL THEN 0.5   -- flatt tun: nøytralt
                        ELSE 0.0 END AS aspect_f,
                   coalesce(over_veg_maks, false) AS over_veg_maks,
                   moh > {kr['moh_maks']} AS over_moh,
                   coalesce(slope_deg, 0) > {kr['slope_max']} AS for_bratt,
                   coalesce(naboer_200m, 0) > {kr.get('naboer_maks_200m', 6)} AS tettbygd
            FROM kandidat
        )
        SELECT bygningid, kommunenr,
               round({w['w_sol']} * sol_f + {w['w_innmark']} * innmark_f + {w['w_forfall']} * forfall_f + {w['w_aspect']} * aspect_f, 4) AS total,
               sol_f, innmark_f, forfall_f, aspect_f,
               tettbygd,
               (over_veg_maks OR over_moh OR for_bratt OR tettbygd) AS utenfor_kriterier,
               row_number() OVER (ORDER BY (over_veg_maks OR over_moh OR for_bratt OR tettbygd), total DESC) AS rank
        FROM k
    """)
    lag_views(con)
    n = dict(scoret=con.execute("SELECT count(*) FROM score").fetchone()[0],
             utenfor=con.execute("SELECT count(*) FROM score WHERE utenfor_kriterier").fetchone()[0],
             tettbygd=con.execute("SELECT count(*) FROM score WHERE tettbygd").fetchone()[0],
             forfall_tilgjengelig=har_forfall)
    print("Steg 7a score:", n)
    con.close()
    return n


if __name__ == "__main__":
    steg7_score()
