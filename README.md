# Ødehus i Buskerud

Finner mulige forlatte hus, småbruk og setre i Buskerud fra åpne kartdata, og rangerer dem etter sol,
dyrkbar jord, tilkomst og tegn til forfall. Målet er et sted for blomster- og grønnsakshage, med
restaurering eller nybygg.

**Prospektene kan ses og vurderes her:** https://snkpipefish.github.io/odehus-buskerud/

Siden er en satellittvisning i samme stil som [GULLØYE](https://github.com/Snkpipefish/gulloye)
(CesiumJS-globus med HUD, inspirert av gods-eye-view): hvert prospekt har et satellittutsnitt
(Esri World Imagery, ca. 300 × 300 m) med sikte og målestokk, et galleri med alle bildene og filtre,
og et MÅL-panel med nøkkeltall, forfallsvurdering og lenker til nyere flyfoto (Norge i bilder),
Kartverkets eiendomsside, Norgeskart og Google Maps. Den som ser på trykker Ja / Kanskje / Nei og
skriver notat per tun; vurderingene lagres i nettleseren og kan lastes ned som fil eller kopieres
som tekst og sendes tilbake.

Laget MATRIKKELBYGG viser alle bygningspunkter fra Matrikkelen innen 160 m rundt valgt mål, på globusen og oppå satellittbildet, med bygningstype; det valgte bygget er merket gult. Slik ser man hvor bygningen *skal* stå, også der satellittbildet viser bare skog eller plen. Alle prospektene på siden er vurdert manuelt mot satellittbilde eller flyfoto (merket «sett»). Tun som er sjekket mot bilde og viser seg å være i bruk, er tatt ut av siden; igjen står steder med tegn til forfall eller der bygningen er borte (tomter). Globusen bruker flatt kart uten terrengmodell, så markørene ligger fast mot bildet ved zoom.

Bildene lages med `python -m odehus.satbilder` (3 × 3 fliser sys sammen og beskjæres rundt
bygningspunktet, som i GULLØYE sin satellittsjekk) og ligger i `docs/img/`.

## Hvordan det er laget

Pipelinen (`src/odehus/`) kjører per kommune, se `PLAN-odehus-buskerud.md`:

1. Last ned og indekser Matrikkelen (bygning, teig, adresse) fra Geonorge → DuckDB
2. Filtrer bolighus på tun (enebolig, våningshus, seterhus), flagg SEFRAK og status
3. Terreng (DTM fra Kartverkets WCS) og sol (egen horisont + PVGIS)
4. Jord: AR50 på teigen og AR5 rundt tunet (NIBIO)
5. Tilkomst: avstand til bilvei (NVDB), naboer og hytter innen 200 m
6. Forfall: laserproxy (nDSM) for alle, manuell flyfoto-vurdering for topp-lister
7. Score, eksport (CSV, GeoJSON, kart) og rapport
8. Utrulling til alle 18 kommuner og samlet fylkesliste; `python -m odehus.web` lager `docs/data.json`, `python -m odehus.satbilder` lager `docs/img/`

```bash
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m odehus.pipeline alle
.venv/bin/python -m odehus.fylke
.venv/bin/python -m odehus.web
.venv/bin/python -m odehus.satbilder
```

Kjøring krever ingen nøkler eller innlogging. Nedlastede data (`data/`) og resultatfiler (`out/`)
er ikke med i repoet. Datasett og lisenser står i `LICENSES.md`. Ingen persondata lagres: bare
matrikkelnummer, bruksnavn og beregnede verdier. Eierforhold må slås opp manuelt på seeiendom.no.

Rangeringen er en hjelp til å lete, ikke en fasit. Laserproxyen for forfall bommer ofte i lavlandet
(nye hus er yngre enn laserdataene); flyfoto må alltid sjekkes.
