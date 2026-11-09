"""Steg 7b: eksport til CSV, GeoJSON og folium-kart."""
from __future__ import annotations

import json
from pathlib import Path

import folium
import pandas as pd

from . import config as C
from .buildings import kodeliste_bygningstype, lenker
from .ingest import connect
from .views import lag_views

KOLONNER = ["rank", "total", "kommunenr", "gnr", "bnr", "fnr", "bruksnavn", "type", "bygningstype", "byggeaar", "sefrak",
            "status", "moh", "aspect_deg", "slope_deg", "soltimer_mars", "soltimer_juli", "innstraling_apr_sep", "sol_pct",
            "innmark_daa", "ar50_innmark_daa", "ar5_naer_innmark_daa", "innmark_naer_tun", "teig_daa",
            "veg_m", "veg_kategori", "veg_offentlig_m", "naboer_200m", "hytter_200m",
            "forfall_score", "forfall_begrunnelse", "forfall_kilde", "bygg_hoyde_m", "gjengroing_tun_pct", "utenfor_kriterier", "tettbygd", "lat", "lon",
            "lenke_norgeibilder", "lenke_seeiendom", "lenke_norgeskart", "lenke_google"]


def _seeiendom(knr: str, gnr, bnr, fnr) -> str:
    return f"https://seeiendom.kartverket.no/eiendom/{knr}/{gnr}/{bnr}/{fnr or 0}/0"


def hent_df(con, kommunenr: str | None) -> pd.DataFrame:
    lag_views(con)
    where = f"WHERE k.kommunenr = '{kommunenr}'" if kommunenr else ""
    df = con.execute(f"SELECT k.* EXCLUDE (geom, teig_geom), ST_AsGeoJSON(k.teig_geom) AS teig_geojson FROM kandidat k {where} ORDER BY rank").df()
    typer = kodeliste_bygningstype()
    kort = {111: "Enebolig", 113: "Våningshus", 171: "Seterhus/sel", 163: "Våningshus (fritidsbruk)", 162: "Helårsbolig (fritidsbruk)"}
    df["bygningstype"] = df["type"].map(lambda t: kort.get(int(t)) or typer.get(int(t), "?")[:40])
    L = df.apply(lambda r: lenker(r.x, r.y), axis=1, result_type="expand")
    df["lenke_norgeibilder"], df["lenke_norgeskart"], df["lenke_google"] = L["norgeibilder"], L["norgeskart"], L["google"]
    df["lenke_seeiendom"] = [_seeiendom(k, g, b, f) for k, g, b, f in zip(df.kommunenr, df.gnr, df.bnr, df.fnr)]
    for c in KOLONNER:
        if c not in df.columns:
            df[c] = None
    return df


def steg7_export(kommunenr: str, cfg: dict | None = None) -> dict:
    cfg = cfg or C.load()
    out = C.ROOT / cfg["paths"]["out"]
    out.mkdir(exist_ok=True)
    con = connect(C.db_path(cfg))
    df = hent_df(con, kommunenr)
    con.close()
    stem = f"{kommunenr}"
    df[KOLONNER].to_csv(out / f"{stem}_shortlist.csv", index=False, encoding="utf-8")

    feats = []
    for r in df.itertuples():
        props = {c: (None if pd.isna(getattr(r, c)) else getattr(r, c)) for c in KOLONNER if c not in ("teig_geojson",)}
        props = {k: (v.item() if hasattr(v, "item") else v) for k, v in props.items()}
        feats.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[r.lon, r.lat]), properties=props))
    (out / f"{stem}_kandidater.geojson").write_text(json.dumps(dict(type="FeatureCollection", features=feats), ensure_ascii=False), encoding="utf-8")

    _kart(df, out / "kart.html")
    return dict(rader=len(df), csv=str(out / f"{stem}_shortlist.csv"), geojson=str(out / f"{stem}_kandidater.geojson"), kart=str(out / "kart.html"))


def _farge(total: float) -> str:
    t = max(0.0, min(1.0, (total - 0.2) / 0.5))
    return f"#{int(220 - 180 * t):02x}{int(60 + 150 * t):02x}40"


def _kart(df: pd.DataFrame, sti: Path) -> None:
    m = folium.Map(location=[df.lat.mean(), df.lon.mean()], zoom_start=11, tiles=None)
    folium.TileLayer("https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png",
                     name="Kartverket topo", attr="© Kartverket").add_to(m)
    folium.TileLayer("OpenStreetMap", name="OSM").add_to(m)
    gruppe = {g: folium.FeatureGroup(name=g, show=(g == "topp 100")) for g in ("topp 100", "101–300", "øvrige", "utenfor kriterier")}
    for r in df.itertuples():
        g = "utenfor kriterier" if r.utenfor_kriterier else "topp 100" if r.rank <= 100 else "101–300" if r.rank <= 300 else "øvrige"
        html = f"<b>#{r.rank} {r.bruksnavn or ''}</b> {r.kommunenr}-{r.gnr}/{r.bnr}{'/' + str(r.fnr) if r.fnr else ''}<br>"
        html += f"{r.bygningstype} · status {r.status} · {'SEFRAK' if r.sefrak else ''}<br>"
        html += f"score {r.total:.2f} · sol_pct {r.sol_pct} · mars {r.soltimer_mars} t · innmark {r.innmark_daa} daa<br>"
        html += f"moh {r.moh:.0f} · aspect {('%.0f' % r.aspect_deg) if pd.notna(r.aspect_deg) else '–'}° · helning {r.slope_deg:.1f}°<br>"
        html += f"veg {r.veg_m:.0f} m ({r.veg_kategori}) · naboer {r.naboer_200m}<br>"
        if pd.notna(r.forfall_score):
            html += f"forfall {r.forfall_score}: {r.forfall_begrunnelse}<br>"
        for navn, k in (("norgeibilder", r.lenke_norgeibilder), ("seeiendom", r.lenke_seeiendom), ("norgeskart", r.lenke_norgeskart), ("google", r.lenke_google)):
            html += f'<a href="{k}" target="_blank">{navn}</a> · '
        folium.CircleMarker([r.lat, r.lon], radius=6 if r.rank <= 100 else 4, color=_farge(r.total), fill=True, fill_opacity=0.85,
                            popup=folium.Popup(html, max_width=380), tooltip=f"#{r.rank} {r.bruksnavn or ''} ({r.total:.2f})").add_to(gruppe[g])
    for fg in gruppe.values():
        fg.add_to(m)
    folium.LayerControl().add_to(m)
    m.save(str(sti))


if __name__ == "__main__":
    import sys

    print(steg7_export(sys.argv[1] if len(sys.argv) > 1 else "3336"))
