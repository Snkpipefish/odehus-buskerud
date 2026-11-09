"""Samlet eksport for hele fylket når alle kommuner er kjørt:
out/buskerud_shortlist.csv, out/buskerud_kandidater.geojson, out/kart_buskerud.html (topp 1500), out/buskerud_topp50.md.
Kjør: python -m odehus.fylke"""
from __future__ import annotations

import json

import pandas as pd

from . import config as C
from .export import KOLONNER, _kart, hent_df
from .ingest import connect
from .rapport import topp
from .score import steg7_score


def main(n_kart: int = 1500) -> None:
    cfg = C.load()
    steg7_score()
    out = C.ROOT / cfg["paths"]["out"]
    con = connect(C.db_path(cfg))
    df = hent_df(con, None)
    con.close()
    df[KOLONNER].to_csv(out / "buskerud_shortlist.csv", index=False, encoding="utf-8")
    feats = []
    for r in df.itertuples():
        props = {c: (None if pd.isna(getattr(r, c)) else getattr(r, c)) for c in KOLONNER}
        props = {k: (v.item() if hasattr(v, "item") else v) for k, v in props.items()}
        feats.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[r.lon, r.lat]), properties=props))
    (out / "buskerud_kandidater.geojson").write_text(json.dumps(dict(type="FeatureCollection", features=feats), ensure_ascii=False), encoding="utf-8")
    _kart(df[df["rank"] <= n_kart], out / "kart_buskerud.html")
    topp(None, 50)
    print("fylke:", dict(kandidater=len(df), kommuner=df.kommunenr.nunique(), kart_punkter=int((df["rank"] <= n_kart).sum())))
    print(df.groupby("kommunenr").size().to_dict())


if __name__ == "__main__":
    main()
