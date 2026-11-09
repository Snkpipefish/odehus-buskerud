"""Markdown-rapport med de N høyest rangerte kandidatene, med lenker for manuell kontroll.
Kjør: python -m odehus.rapport 3336 20"""
from __future__ import annotations

import sys
from datetime import date

from . import config as C
from .export import hent_df
from .ingest import connect


def topp(kommunenr: str | None, n: int = 20, cfg: dict | None = None):
    cfg = cfg or C.load()
    con = connect(C.db_path(cfg))
    df = hent_df(con, kommunenr)
    con.close()
    df = df[~df.utenfor_kriterier.fillna(False)].head(n)
    navn = kommunenr or "buskerud"
    L = [f"# Topp {n} kandidater – {'kommune ' + kommunenr if kommunenr else 'hele Buskerud'} ({date.today()})", "",
         "Forfall er en proxy fra laserdata (nDSM), ikke ortofoto. Sjekk hver rad i norgeibilder/Google før du godkjenner. Rader med flere enn 6 bolighus innen 200 m (boligfelt) er holdt utenfor lista, men ligger i CSV og kart.", "",
         "| # | Score | Kommune | Gnr/bnr | Navn | Type | SEFRAK | moh | Aspect | Sol mars (t) | Sol-pct | Innmark daa | Veg m | Naboer | Forfall | Lenker |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    import pandas as pd

    def v(x, fmt="{:.0f}", tom="–"):
        return tom if x is None or (isinstance(x, float) and x != x) or x is pd.NA else fmt.format(x)

    for r in df.itertuples():
        asp = v(r.aspect_deg, "{:.0f}°", "flat")
        if pd.isna(r.forfall_score):
            forfall = "–"
        elif r.forfall_kilde == "visuell":
            forfall = f"{int(r.forfall_score)} ({r.forfall_begrunnelse})"
        else:
            forfall = f"{int(r.forfall_score)} proxy"
        L.append(f"| {r.rank} | {r.total:.2f} | {r.kommunenr} | {r.gnr}/{r.bnr}{'/' + str(r.fnr) if r.fnr else ''} | {r.bruksnavn or ''} | {r.bygningstype} | "
                 f"{'ja' if r.sefrak is True else ''} | {v(r.moh)} | {asp} | {v(r.soltimer_mars, '{:.1f}')} | {v(r.sol_pct)} | {v(r.innmark_daa)} | "
                 f"{v(r.veg_m)} ({r.veg_kategori or '–'}) | {v(r.naboer_200m)} | {forfall} | "
                 f"[flyfoto]({r.lenke_norgeibilder}) · [eiendom]({r.lenke_seeiendom}) · [kart]({r.lenke_norgeskart}) · [google]({r.lenke_google}) |")
    ut = C.ROOT / cfg["paths"]["out"] / f"{navn}_topp{n}.md"
    ut.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("skrevet", ut)
    return ut


if __name__ == "__main__":
    a = sys.argv[1:]
    topp(a[0] if a else "3336", int(a[1]) if len(a) > 1 else 20)
