"""Nedlasting av åpne datasett. Alt caches i data/raw/<kommunenr>/.

Verifisert 2026-11-07:
- Kommuneliste: https://api.kartverket.no/kommuneinfo/v1/fylker/33  (felt: kommunenummer, kommunenavn)
- Matrikkel-datasett (åpne, uten innlogging):
  https://nedlasting.geonorge.no/geonorge/Basisdata/<Datasett>/GML/Basisdata_<knr>_<Kommune>_25833_<Datasett>_GML.zip
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import requests

from .config import raw_dir

log = logging.getLogger(__name__)

KARTVERKET_FYLKE = "https://api.kartverket.no/kommuneinfo/v1/fylker/{fylke}"
GEONORGE_BASIS = (
    "https://nedlasting.geonorge.no/geonorge/Basisdata/{ds}/{fmt}/"
    "Basisdata_{knr}_{navn}_25833_{ds}_{fmt}.zip"
)

MATRIKKEL_DATASETT = {
    "bygning": "MatrikkelenBygning",
    "teig": "MatrikkelenEiendomskartTeig",
    "adresse": "MatrikkelenAdresse",
}

_session = requests.Session()
_session.headers["User-Agent"] = "odehus-finner/0.1 (open-data terrain analysis)"  # kun ASCII: PVGIS-WAF avviser æøå i header


def kommuner_i_fylke(fylkesnr: str) -> dict[str, str]:
    """{kommunenummer: kommunenavn} for fylket, hentet live fra Kartverket."""
    r = _session.get(KARTVERKET_FYLKE.format(fylke=fylkesnr), timeout=30)
    r.raise_for_status()
    d = r.json()
    return {k["kommunenummer"]: k["kommunenavn"] for k in d["kommuner"]}


def _url_navn(kommunenavn: str) -> str:
    """Geonorge-filnavn: æøå -> ascii, mellomrom -> understrek. Verifisert 2026-11-07 for alle 18
    Buskerud-kommuner (Krodsherad, Fla, Al, Nore_og_Uvdal, Ovre_Eiker)."""
    t = str.maketrans({"æ": "ae", "ø": "o", "å": "a", "Æ": "Ae", "Ø": "O", "Å": "A"})
    return kommunenavn.translate(t).replace(" ", "_")


def hent_matrikkel(cfg: dict, kommunenr: str, kommunenavn: str, hva: str, fmt: str = "GML") -> Path:
    """Laster ned ett Matrikkel-datasett for en kommune og pakker ut. Returnerer sti til GML-fila."""
    ds = MATRIKKEL_DATASETT[hva]
    out = raw_dir(cfg, kommunenr)
    zpath = out / f"{ds}_{fmt}.zip"
    if not zpath.exists() or zpath.stat().st_size == 0:
        url = GEONORGE_BASIS.format(ds=ds, fmt=fmt, knr=kommunenr, navn=_url_navn(kommunenavn))
        log.info("laster ned %s", url)
        with _session.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "zip" not in ctype:
                raise RuntimeError(f"uventet content-type {ctype!r} fra {url}")
            with open(zpath, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".gml", ".gdb"))]
        if not names:
            raise RuntimeError(f"ingen GML i {zpath}: {z.namelist()}")
        target = out / names[0]
        if not target.exists():
            z.extractall(out)
    return target


def hent_alle_matrikkel(cfg: dict, kommunenr: str, kommunenavn: str) -> dict[str, Path]:
    return {hva: hent_matrikkel(cfg, kommunenr, kommunenavn, hva) for hva in MATRIKKEL_DATASETT}


# ---------------------------------------------------------------- Høyde (moh)
HOYDE_API = "https://ws.geonorge.no/hoydedata/v1/punkt"
HOYDE_BATCH = 50


def hoyde_punkter(cfg: dict, kommunenr: str, punkter: list[tuple[float, float]]) -> dict[tuple[float, float], dict]:
    """Terrenghøyde (moh) for punkter i EPSG:25833 fra Kartverkets høyde-API (DTM1/DTM10).
    Verifisert 2026-11-07: GET ?koordsys=25833&punkter=[[x,y],...] gir {"punkter":[{x,y,z,datakilde,terreng}]}.
    Svar caches i data/derived/<knr>/hoyde_cache.json (nøkkel "x,y" avrundet til 0.1 m)."""
    import json

    from .config import derived_dir

    cache_fil = derived_dir(cfg, kommunenr) / "hoyde_cache.json"
    cache: dict[str, dict] = json.loads(cache_fil.read_text()) if cache_fil.exists() else {}

    def nokkel(p):
        return f"{p[0]:.1f},{p[1]:.1f}"

    mangler = [p for p in punkter if nokkel(p) not in cache]
    for i in range(0, len(mangler), HOYDE_BATCH):
        batch = mangler[i : i + HOYDE_BATCH]
        r = _session.get(
            HOYDE_API,
            params={"koordsys": 25833, "geojson": "false",
                    "punkter": json.dumps([[round(x, 1), round(y, 1)] for x, y in batch])},
            timeout=60,
        )
        r.raise_for_status()
        svar = r.json().get("punkter", [])
        if len(svar) != len(batch):
            raise RuntimeError(f"høyde-API ga {len(svar)} svar for {len(batch)} punkter")
        for p, s in zip(batch, svar):
            cache[nokkel(p)] = {"z": s.get("z"), "datakilde": s.get("datakilde"), "terreng": s.get("terreng")}
        cache_fil.write_text(json.dumps(cache))
        log.info("høyde: %d/%d", min(i + HOYDE_BATCH, len(mangler)), len(mangler))
    return {p: cache[nokkel(p)] for p in punkter}
