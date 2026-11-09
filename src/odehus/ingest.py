"""Leser Matrikkel-GML (Bygningspunkt, Teig, Adresse) med lxml og laster inn i DuckDB (spatial).

Feltnavn er verifisert mot faktiske GML-filer for Rollag (produktspesifikasjon 20211101 / 20200501).
Merk: Bygningspunkt-produktet inneholder IKKE byggeår. Feltet `byggeaar` settes til NULL og
`sefrak` (harSefrakminne) brukes som alders-proxy.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import duckdb
import pandas as pd
from lxml import etree
from shapely.geometry import MultiPolygon, Point, Polygon

log = logging.getLogger(__name__)
GML = "http://www.opengis.net/gml/3.2"


def _local(tag) -> str:
    if not isinstance(tag, str):  # kommentarer/PI har funksjon som tag
        return ""
    return tag.rsplit("}", 1)[-1]


def iter_features(path: Path, tags: set[str]) -> Iterator[etree._Element]:
    """Strømmer gjennom gml:featureMember og gir ut elementer med lokalnavn i `tags`."""
    for _, el in etree.iterparse(str(path), events=("end",)):
        if _local(el.tag) in tags:
            yield el
            # frigjør minne
            el.clear()
            parent = el.getparent()
            while parent is not None and el.getprevious() is not None:
                del parent[0]


def _txt(el: etree._Element, local: str) -> str | None:
    """Første etterkommer med gitt lokalnavn (ikke-rekursivt forvirrende navn som kommunenummer
    håndteres ved at kalleren begrenser søket til riktig delelement)."""
    for e in el.iter():
        if _local(e.tag) == local and e.text and e.text.strip():
            return e.text.strip()
    return None


def _child(el: etree._Element, local: str) -> etree._Element | None:
    for e in el:
        if _local(e.tag) == local:
            return e
    return None


def _pos(el: etree._Element) -> tuple[float, float] | None:
    rp = _child(el, "representasjonspunkt")
    if rp is None:
        return None
    for e in rp.iter():
        if _local(e.tag) == "pos" and e.text:
            x, y = e.text.split()[:2]
            return float(x), float(y)
    return None


def _ring(ring_el: etree._Element) -> list[tuple[float, float]]:
    for e in ring_el.iter():
        if _local(e.tag) == "posList" and e.text:
            v = list(map(float, e.text.split()))
            return list(zip(v[0::2], v[1::2]))
    return []


def _surface(el: etree._Element):
    omr = _child(el, "område")
    if omr is None:
        return None
    polys = []
    for patch in omr.iter():
        if _local(patch.tag) != "PolygonPatch":
            continue
        ext, ints = None, []
        for sub in patch:
            ln = _local(sub.tag)
            if ln == "exterior":
                ext = _ring(sub)
            elif ln == "interior":
                ints.append(_ring(sub))
        if ext and len(ext) >= 4:
            polys.append(Polygon(ext, [r for r in ints if len(r) >= 4]))
    if not polys:
        return None
    geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def _bool(s: str | None) -> bool | None:
    return None if s is None else s.lower() == "true"


# ---------------------------------------------------------------- Bygning
def les_bygning(path: Path) -> pd.DataFrame:
    rows = []
    for el in iter_features(path, {"Bygning"}):
        xy = _pos(el)
        if xy is None:
            continue
        ident = _child(el, "identBygning")
        bruksenheter = [b for b in el if _local(b.tag) == "bruksenhet"]
        me_ids = [_txt(b, "matrikkelenhetId") for b in bruksenheter]
        adr_ids = [_txt(b, "adresseId") for b in bruksenheter]
        sefrak_el = _child(el, "sefrakIdent")
        rows.append(
            dict(
                bygningid=int(_txt(ident, "bygningId")) if ident is not None else None,
                bygningsnummer=int(_txt(el, "bygningsnummer") or 0),
                uuid=_txt(el, "uuidBygning"),
                kommunenr=_txt(el, "kommunenummer"),
                bygningstype=int(_txt(el, "bygningstype") or 0),
                status=_txt(el, "bygningsstatus"),
                sefrak=_bool(_txt(el, "harSefrakminne")) or False,
                sefrak_minne_id=_txt(sefrak_el, "sefrakMinneId") if sefrak_el is not None else None,
                kulturminne=_bool(_txt(el, "harKulturminne")) or False,
                opprinnelse=_txt(el, "opprinnelse"),
                naringsgruppe=_txt(el, "naringsgruppe"),
                stedfesting_verifisert=_bool(_txt(el, "stedfestingVerifisert")),
                antall_bruksenheter=len(bruksenheter),
                matrikkelenhet_ids=[int(m) for m in me_ids if m],
                adresse_ids=[int(a) for a in adr_ids if a],
                x=xy[0],
                y=xy[1],
                geom_wkb=Point(xy).wkb,
            )
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- Teig
def les_teig(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returnerer (teig, teig_matrikkelenhet). Teig kan ha flere matrikkelenheter."""
    teiger, koblinger = [], []
    for el in iter_features(path, {"Teig"}):
        geom = _surface(el)
        if geom is None:
            continue
        teig_id = int(_txt(_child(el, "identTeig"), "teigId"))
        xy = _pos(el)
        mes = [m for m in el if _local(m.tag) == "matrikkelenhet"]
        first = None
        for m in mes:
            me = _child(m, "Matrikkelenhet")
            if me is None:
                me = m
            d = dict(
                teig_id=teig_id,
                matrikkelenhet_id=int(_txt(me, "matrikkelenhetId") or 0),
                kommunenr=_txt(me, "kommunenummer"),
                gnr=int(_txt(me, "gardsnummer") or 0),
                bnr=int(_txt(me, "bruksnummer") or 0),
                fnr=int(_txt(me, "festenummer") or 0),
                snr=int(_txt(me, "seksjonsnummer") or 0),
                bruksnavn=_txt(me, "bruksnavn"),
                matrikkelenhetstype=_txt(me, "matrikkelenhetstype"),
                kulturminne=_bool(_txt(me, "harKulturminne")) or False,
            )
            koblinger.append(d)
            first = first or d
        areal_el = _child(el, "teigareal")
        teiger.append(
            dict(
                teig_id=teig_id,
                kommunenr=_txt(el, "kommunenummer"),
                gnr=first["gnr"] if first else None,
                bnr=first["bnr"] if first else None,
                fnr=first["fnr"] if first else None,
                bruksnavn=first["bruksnavn"] if first else None,
                matrikkelenhetstype=first["matrikkelenhetstype"] if first else None,
                antall_matrikkelenheter=len(mes),
                flere_matrikkelenheter=_bool(_txt(el, "teigMedFlereMatrikkelenheter")) or False,
                matrikkelnummer_tekst=_txt(el, "matrikkelnummerTekst"),
                areal_m2=float(_txt(areal_el, "lagretBeregnetAreal")) if areal_el is not None and _txt(areal_el, "lagretBeregnetAreal") else geom.area,
                noyaktighet=_txt(el, "noyaktighetsklasseTeig"),
                x=xy[0] if xy else geom.representative_point().x,
                y=xy[1] if xy else geom.representative_point().y,
                geom_wkb=geom.wkb,
            )
        )
    return pd.DataFrame(teiger), pd.DataFrame(koblinger)


# ---------------------------------------------------------------- Adresse
def les_adresse(path: Path) -> pd.DataFrame:
    rows = []
    for el in iter_features(path, {"Vegadresse", "Matrikkeladresse"}):
        xy = _pos(el)
        if xy is None:
            continue
        mnr = _child(el, "matrikkelnummerAdresse")
        rows.append(
            dict(
                adresse_id=int(_txt(_child(el, "identifikasjonAdresse"), "adresseId")),
                adressetype=_local(el.tag),
                adressetekst=_txt(el, "adresseTekst"),
                kommunenr=_txt(el, "kommunenummer"),
                gnr=int(_txt(mnr, "gardsnummer") or 0) if mnr is not None else None,
                bnr=int(_txt(mnr, "bruksnummer") or 0) if mnr is not None else None,
                fnr=int(_txt(mnr, "festenummer") or 0) if mnr is not None else None,
                postnummer=_txt(el, "postnummer"),
                poststed=_txt(el, "poststed"),
                grunnkrets=_txt(el, "grunnkretsnavn"),
                x=xy[0],
                y=xy[1],
                geom_wkb=Point(xy).wkb,
            )
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- DuckDB
def connect(db: Path, vent_sek: float = 1800) -> duckdb.DuckDBPyConnection:
    """Åpner DuckDB (én skriver om gangen). Venter på låsen i inntil vent_sek sekunder, så
    bakgrunnskjøringer (utrulling) og interaktivt arbeid kan dele databasen."""
    import time

    t0 = time.time()
    while True:
        try:
            con = duckdb.connect(str(db))
            break
        except duckdb.IOException as e:
            if "lock" not in str(e).lower() or time.time() - t0 > vent_sek:
                raise
            time.sleep(3)
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


def _last_inn(con, navn: str, df: pd.DataFrame, kommunenr: str) -> None:
    """Erstatter radene for kommunen i tabellen `navn` (geom fra geom_wkb)."""
    con.register("_df", df)
    cols = [c for c in df.columns if c != "geom_wkb"]
    sel = ", ".join(cols) + ", ST_GeomFromWKB(geom_wkb) AS geom"
    exists = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [navn]
    ).fetchone()[0]
    if exists:
        con.execute(f"DELETE FROM {navn} WHERE kommunenr = ?", [kommunenr])
        con.execute(f"INSERT INTO {navn} SELECT {sel} FROM _df")
    else:
        con.execute(f"CREATE TABLE {navn} AS SELECT {sel} FROM _df")
    con.unregister("_df")


def last_kommune(con, kommunenr: str, filer: dict[str, Path]) -> dict[str, int]:
    """Leser de tre GML-filene og bygger tabellene bygg_raw, teig, teig_matrikkelenhet, adresse og bygg."""
    n = {}
    # Kommunefilene kan inneholde nabokommunens grensebygg; behold bare egen kommune så upsert per kommune blir rent.
    b = les_bygning(filer["bygning"])
    b = b[b.kommunenr == kommunenr].reset_index(drop=True)
    _last_inn(con, "bygg_raw", b, kommunenr)
    n["bygg_raw"] = len(b)

    t, tm = les_teig(filer["teig"])
    t = t[t.kommunenr == kommunenr].reset_index(drop=True)
    tm = tm[tm.teig_id.isin(t.teig_id)].reset_index(drop=True)
    _last_inn(con, "teig", t, kommunenr)
    con.register("_tm", tm)
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='teig_matrikkelenhet'").fetchone()[0]:
        con.execute("DELETE FROM teig_matrikkelenhet WHERE kommunenr = ?", [kommunenr])
        con.execute("INSERT INTO teig_matrikkelenhet SELECT * FROM _tm")
    else:
        con.execute("CREATE TABLE teig_matrikkelenhet AS SELECT * FROM _tm")
    con.unregister("_tm")
    n["teig"] = len(t)
    n["teig_matrikkelenhet"] = len(tm)

    a = les_adresse(filer["adresse"])
    a = a[a.kommunenr == kommunenr].reset_index(drop=True)
    _last_inn(con, "adresse", a, kommunenr)
    n["adresse"] = len(a)

    bygg_tabell(con)
    n["bygg"] = con.execute("SELECT count(*) FROM bygg WHERE kommunenr = ?", [kommunenr]).fetchone()[0]
    return n


def bygg_tabell(con) -> None:
    """Tabell `bygg` iht. briefen: bygningsid, kommunenr, type, byggeår, status, sefrak, x, y, teig_id, gnr, bnr.

    teig_id settes ved punkt-i-polygon (bygget ligger på teigen). Der punktet treffer flere teiger
    (overlapp/unøyaktighet) velges teigen hvis matrikkelenhet matcher byggets bruksenhet, ellers minste teig.
    """
    try:
        con.execute("CREATE INDEX IF NOT EXISTS teig_rtree ON teig USING RTREE (geom)")
    except Exception as e:  # eldre spatial-utgave uten RTREE
        log.warning("ingen RTREE-indeks: %s", e)
    con.execute(
        """
        CREATE OR REPLACE TABLE bygg AS
        WITH kand AS (
            SELECT b.bygningid, t.teig_id, t.gnr, t.bnr, t.fnr, t.bruksnavn, t.areal_m2,
                   t.flere_matrikkelenheter,
                   EXISTS (SELECT 1 FROM teig_matrikkelenhet tm
                           WHERE tm.teig_id = t.teig_id
                             AND list_contains(b.matrikkelenhet_ids, tm.matrikkelenhet_id)) AS me_match,
                   row_number() OVER (
                       PARTITION BY b.bygningid
                       ORDER BY (EXISTS (SELECT 1 FROM teig_matrikkelenhet tm
                                         WHERE tm.teig_id = t.teig_id
                                           AND list_contains(b.matrikkelenhet_ids, tm.matrikkelenhet_id))) DESC,
                                t.areal_m2 ASC) AS rn
            FROM bygg_raw b
            JOIN teig t ON b.kommunenr = t.kommunenr AND ST_Within(b.geom, t.geom)
        )
        SELECT b.bygningid, b.bygningsnummer, b.kommunenr,
               b.bygningstype AS type,
               NULL::INTEGER AS byggeaar,          -- finnes ikke i åpne Bygningspunkt
               b.status, b.sefrak, b.sefrak_minne_id, b.kulturminne, b.opprinnelse,
               b.x, b.y, b.geom,
               k.teig_id, k.gnr, k.bnr, k.fnr, k.bruksnavn,
               k.areal_m2 AS teig_areal_m2, k.flere_matrikkelenheter AS teig_flere_me,
               k.me_match AS teig_me_match,
               b.matrikkelenhet_ids, b.adresse_ids, b.antall_bruksenheter
        FROM bygg_raw b
        LEFT JOIN kand k ON k.bygningid = b.bygningid AND k.rn = 1
        """
    )

