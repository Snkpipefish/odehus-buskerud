# Ødehus-finner – Buskerud (kartleting + sol + jord)

Du er Claude Code. Dette er prosjektbriefen. Les hele før du gjør noe.

## Mål

Finne sannsynlig fraflyttede/forfalne boliger og småbruk i Buskerud fylke ved hjelp av
åpne kart- og satellittdata, og rangere dem etter solforhold og dyrkbar jord.
Sluttprodukt: en rangert shortlist (CSV + GeoJSON + HTML-kart) som jeg går gjennom manuelt
i norgeibilder.no / Google Earth og seeiendom.no.

## Avgrensning – dette gjør vi IKKE

- Ingen scraping av finn.no, 1881.no, gulesider.no eller andre tjenester som forbyr det.
- Ingen bulk-uttak fra grunnboken. Eieroppslag gjøres manuelt av meg på seeiendom.no (BankID).
- Ingen persondata (navn, telefon, fødselsdato) lagres i repoet.
- Ingen vurdering av bygg uten koordinater fra offisielle registre.
- Vi starter med Buskerud. Ikke generaliser til hele landet før pipelinen virker på én kommune.

## Kriterier (defaults i `config.yaml`, alle justerbare)

| Felt | Default | Kommentar |
|---|---|---|
| fylke | 33 Buskerud | kommunenr 3301–3338, hent gjeldende liste fra Kartverket |
| bygningstyper | 113 våningshus, 111 enebolig, 171 seterhus | Matrikkel-koder, verifiser mot Kartverkets kodeliste |
| byggeår | < 1960 eller ukjent | |
| bygningsstatus | ekskluder revet/brent/flyttet | |
| moh | ≤ 700 | over dette er grønnsakdyrking marginalt |
| helningsretning (aspect) | foretrukket 135–225° (SØ–SV), akseptabelt 90–270° | beregnes på tunet, ikke på hele teigen |
| helning (slope) | 1–20° | |
| innmark på teigen | ≥ 5 daa (AR5 arealtype 21+22+23) | fulldyrka + overflatedyrka + innmarksbeite |
| avstand til bilvei | ≤ 500 m, flagg > 150 m | Elveg 2.0 |
| ortofoto-epoker | eldste tilgjengelige ≥ 2008 + nyeste | for forfallsvurdering |

## Datakilder (alle åpne, sjekk lisens per datasett og noter i `LICENSES.md`)

| Behov | Kilde | Format |
|---|---|---|
| Bygningspunkt m/type, byggeår, status, SEFRAK-flagg | Geonorge: «Matrikkelen – Bygningspunkt» | GML/FGDB/PostGIS per kommune |
| Eiendomsteiger m/gnr/bnr | Geonorge: «Matrikkelen – Eiendomskart Teig» | samme |
| Adresser | Geonorge: «Matrikkelen – Adresse» | samme |
| Terreng (sol, helning) | Geonorge/hoydedata.no: «DTM 10 Terrengmodell (UTM33)» | GeoTIFF |
| Horisont/solinnstråling | PVGIS API (EU JRC), `printhorizon` og `MRcalc`/`PVcalc` | JSON, gratis, ingen nøkkel |
| Jord | NIBIO: FKB-AR5 (WFS/WMS/nedlasting), evt. «Dyrkbar jord» | vektor |
| Veg | Geonorge: «Elveg 2.0» | vektor |
| Ortofoto (flere årganger) | Norge i bilder WMS/WMTS (`wms.geonorge.no/skwms1/wms.nib`). Sjekk om BAAT-token trengs og om hvert ortofoto-prosjekt er åpent (CC BY) eller Norge digitalt-begrenset. Bruk bare åpne. | raster |
| Gjengroing (valgfritt) | Sentinel-2 NDVI via Copernicus Data Space | raster 10 m |
| Verneverdi | Riksantikvaren: SEFRAK-lag via Geonorge/Kulturminnesøk | vektor |

Alt i EPSG:25833. WGS84 kun mot PVGIS.

## Teknisk oppsett

- Python 3.12, `uv`. Pakker: geopandas, shapely, pyproj, rasterio, numpy, duckdb (spatial),
  requests, pvlib, folium, pyyaml, tqdm.
- Mappestruktur:
  ```
  config.yaml
  data/raw/<kommunenr>/        (git-ignorert)
  data/derived/<kommunenr>/    (git-ignorert)
  out/
  src/odehus/
    download.py    (Geonorge, NIBIO, PVGIS, NIB)
    buildings.py   (filtrering av bygningspunkt)
    terrain.py     (slope/aspect/horisont fra DTM10)
    sun.py         (PVGIS + egen horisont, soltimer)
    soil.py        (AR5 ∩ teig)
    access.py      (avstand til veg, isolasjon)
    imagery.py     (ortofoto-utsnitt per kandidat, to epoker)
    score.py
    export.py      (CSV/GeoJSON/HTML)
  tests/
  LICENSES.md
  ```
- Alle nedlastinger caches. Kjør alt per kommune. Rollag (3336) er testkommune.

## Steg

### Steg 1 – Nedlasting og indeks
1. Hent kommuneliste for Buskerud fra Kartverket. Ikke gjett kommunenumre.
2. Last ned bygningspunkt, teig og adresse for Rollag fra Geonorges nedlastings-API
   (opprett gratis Geonorge-bruker hvis API-et krever det; be meg om innlogging i så fall).
3. Last inn i DuckDB. Lag tabell `bygg` med: bygningsid, kommunenr, type, byggeår, status,
   sefrak (bool), x, y, teig_id, gnr, bnr.
Ferdig når: `SELECT count(*) FROM bygg WHERE type IN (111,113,171)` gir fornuftig tall for Rollag
og 20 tilfeldige rader stemmer med norgeskart.no ved stikkprøve.

### Steg 2 – Filtrering
Anvend kriteriene (type, byggeår, status, moh). Koble bygg → teig. Ta vare på alle
våningshus på teiger med innmark selv om byggeår mangler.
Ferdig når: tabell `kandidat_v1` finnes med teig-geometri.

### Steg 3 – Sol
1. DTM10 for kommunen. Beregn slope og aspect i et 30 m-vindu rundt hvert bygg (tunet).
2. Egen horisontprofil fra DTM10: høyeste terrengvinkel i 16 retninger innen 15 km.
3. PVGIS `printhorizon` + `MRcalc` for hvert punkt (rate-limit, cache). Sammenlign med egen
   horisont; bruk egen horisont der de avviker mye (PVGIS bruker 90 m-terreng).
4. Beregn med pvlib: soltimer over horisont per dag for 1. mars, 1. mai, 1. juli, 1. sept, og
   sum global innstråling apr–sep.
Ferdig når: hvert kandidatbygg har `aspect_deg, slope_deg, soltimer_mars, soltimer_mai,
innstraling_apr_sep, sol_pct` (percentil innen fylket).

### Steg 4 – Jord
AR5 for kommunen. For hver teig: daa arealtype 21, 22, 23 hver for seg og sum. Flagg
teiger der innmarka grenser til tunet (< 50 m).
Ferdig når: `innmark_daa, innmark_naer_tun` er satt på alle kandidater.

### Steg 5 – Tilkomst og isolasjon
Avstand til nærmeste bilveg (Elveg). Antall andre boligbygg innen 200 m. Flagg «uten vinterveg»
om nærmeste veg er privat/skogsbilveg.
Ferdig når: `veg_m, naboer_200m` er satt.

### Steg 6 – Satellitt/ortofoto (kjernen i «kartleting»)
1. For hver kandidat: hent 150 × 150 m utsnitt fra Norge i bilder i to epoker (eldste ≥ 2008,
   nyeste). Bruk kun ortofoto-prosjekter med åpen lisens. Lagre som PNG i `data/derived/.../img/`.
2. Jeg (Claude Code) ser på bildeparene for de 300 høyest rangerte etter steg 3–5 og setter
   `forfall_score` 0–3 med én setnings begrunnelse:
   0 = vedlikeholdt tun, 1 = usikkert, 2 = gjengrodd tun/adkomst eller skadet tak,
   3 = tydelig forfall (tak delvis borte, tun helt gjengrodd, vei borte).
   Sammenlign epokene – økende gjengroing teller mer enn statisk tilstand.
3. Valgfritt: Sentinel-2 NDVI-trend 2017–2025 på innmarka som gjengroingsindikator.
Ferdig når: `forfall_score, forfall_begrunnelse, img_old, img_new` er satt på topp-300.

### Steg 7 – Scoring og eksport
Score (justerbar i config):
```
total = 0.35*sol_pct + 0.25*min(innmark_daa,30)/30 + 0.30*forfall_score/3
        + 0.10*(1 if 135<=aspect<=225 else 0.5 if 90<=aspect<=270 else 0)
```
Eksporter:
- `out/<kommune>_shortlist.csv`: rank, kommune, gnr, bnr, bygningstype, byggeår, moh, aspect,
  slope, soltimer_mars, innmark_daa, veg_m, forfall_score, begrunnelse, lat, lon,
  lenke til norgeibilder.no (sentrert på punktet), lenke til seeiendom.no, lenke til Google Maps.
- `out/<kommune>_kandidater.geojson`
- `out/kart.html` (folium): punkter farget etter total, popup med alle felt og begge
  ortofoto-utsnittene.

### Steg 8 – Utrulling til hele Buskerud
Først når Rollag er ferdig og jeg har godkjent 20 stikkprøver. Kjør deretter steg 1–7 for
alle kommuner, lavlands- og dalkommunene først (Sigdal, Flesberg, Nore og Uvdal, Krødsherad,
Modum, Øvre Eiker, Ringerike, Flå, Nesbyen, Gol, Ål, Hol, Hemsedal), bykommunene sist.

## Arbeidsregler

- Verifiser hvert API/datasett med et lite kall før du bygger kode på det. Ikke anta
  lagnavn, kodelister eller URL-er – slå opp.
- Når noe krever innlogging, token eller betaling: stopp og spør meg.
- Skriv test for hver modul mot Rollag-data før du går videre.
- Loggfør lisens og nedlastingsdato for hvert datasett i `LICENSES.md`.
- Rapporter kort etter hvert steg: antall rader inn/ut, tid, problemer. Ikke lange forklaringer.
- Aldri commit `data/`.

## Start nå

Gjør steg 1 for Rollag (3336). Rapporter antall bygg per type og vis 10 tilfeldige
våningshus som koordinater jeg kan sjekke på norgeskart.no.
