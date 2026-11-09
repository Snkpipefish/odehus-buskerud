"""Bygger samle-viewet `kandidat` (og alias kandidat_v2..v4) fra de tabellene som finnes."""
from __future__ import annotations

TABELLER = {
    "terreng": ("bygningid", "t.moh_dtm, t.slope_deg, t.aspect_deg, t.horisont_egen, t.horisont_maks, t.horisont_sor"),
    "sol": ("bygningid", "s.lat, s.lon, s.horisont_pvgis, s.horisont_avvik_maks, s.horisont_kilde, s.soltimer_mars, s.soltimer_mai, "
                         "s.soltimer_juli, s.soltimer_sept, s.innstraling_apr_sep, s.innstraling_aar, s.sol_pct"),
    "teig_ar50": ("teig_id", "a.ar50_dyrka_daa, a.ar50_beite_daa, a.ar50_innmark_daa, a.ar50_skog_daa, a.ar50_myr_daa"),
    "jord_tun": ("bygningid", "j.ar5_tun_type, j.innmark_naer_tun, j.ar5_naer_fulldyrka_daa, j.ar5_naer_overflatedyrka_daa, "
                              "j.ar5_naer_beite_daa, j.ar5_naer_innmark_daa, j.ar5_naer_antall_flater"),
    "tilkomst": ("bygningid", "ti.veg_m, ti.veg_kategori, ti.veg_type, ti.veg_ref, ti.veg_offentlig_m, ti.naboer_200m, ti.hytter_200m, "
                              "ti.flagg_privat_veg, ti.flagg_uten_vinterveg, ti.flagg_veg_langt, ti.over_veg_maks"),
    "forfall": ("bygningid", "f.forfall_score, f.forfall_begrunnelse, f.forfall_kilde, f.bygg_hoyde_m, f.gjengroing_tun_pct, "
                            "f.gjengroing_naer_pct, f.img_old, f.img_new, f.img_old_aar, f.img_new_aar"),  # + forfall_proxy/visuell via f.* ved behov
    "score": ("bygningid", "sc.total, sc.rank, sc.utenfor_kriterier, sc.tettbygd"),
}
ALIAS = {"terreng": "t", "sol": "s", "teig_ar50": "a", "jord_tun": "j", "tilkomst": "ti", "forfall": "f", "score": "sc"}


def lag_views(con) -> list[str]:
    finnes = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    kolonner = {}
    for t, c in con.execute("SELECT table_name, column_name FROM information_schema.columns").fetchall():
        kolonner.setdefault(t, set()).add(c)
    cols, joins, med = ["k.*"], [], []
    for navn, (nokkel, felter) in TABELLER.items():
        if navn in finnes:
            # ta bare med felter som finnes (tabellen kan være laget av en eldre versjon og lages på nytt senere)
            felter = ", ".join(f for f in felter.split(", ") if f.split(".")[1] in kolonner.get(navn, set()))
            cols.append(felter)
            joins.append(f"LEFT JOIN {navn} {ALIAS[navn]} ON {ALIAS[navn]}.{nokkel} = k.{nokkel}")
            med.append(navn)
    if "teig_ar50" in finnes or "jord_tun" in finnes:
        a = "coalesce(a.ar50_innmark_daa, 0)" if "teig_ar50" in finnes else "0"
        j = "coalesce(j.ar5_naer_innmark_daa, 0)" if "jord_tun" in finnes else "0"
        cols.append(f"greatest({a}, {j}) AS innmark_daa")
    sql = f"SELECT {', '.join(cols)} FROM kandidat_v1 k {' '.join(joins)}"
    con.execute(f"CREATE OR REPLACE VIEW kandidat AS {sql}")
    for v in ("kandidat_v2", "kandidat_v3", "kandidat_v4"):
        con.execute(f"CREATE OR REPLACE VIEW {v} AS SELECT * FROM kandidat")
    return med
