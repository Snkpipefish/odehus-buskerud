# Ødehus i Buskerud

Finner mulige forlatte hus, småbruk og setre i Buskerud fra åpne kartdata, og rangerer dem etter sol,
dyrkbar jord, tilkomst og tegn til forfall. Målet er et sted for blomster- og grønnsakshage, med
restaurering eller nybygg.

**Prospektene kan ses og vurderes her:** https://snkpipefish.github.io/odehus-buskerud/

Siden viser de beste kandidatene innenfor kriteriene med kart, nøkkeltall og lenker til flyfoto
(Norge i bilder), Kartverkets eiendomsside, Norgeskart og Google Maps. Den som ser på kan trykke
Ja / Kanskje / Nei og skrive notat per tun; vurderingene lagres i nettleseren og kan lastes ned som
fil eller kopieres som tekst og sendes tilbake.

## Hvordan det er laget

Pipelinen (`src/odehus/`) kjører per kommune, se `PLAN-odehus-buskerud.md`:

1. Last ned og indekser Matrikkelen (bygning, teig, adresse) fra Geonorge → DuckDB
2. Filtrer bolighus på tun (enebolig, våningshus, seterhus), flagg SEFRAK og status
3. Terreng (DTM fra Kartverkets WCS) og sol (egen horisont + PVGIS)
4. Jord: AR50 på teigen og AR5 rundt tunet (NIBIO)
5. Tilkomst: avstand til bilvei (NVDB), naboer og hytter innen 200 m
6. Forfall: laserproxy (nDSM) for alle, manuell flyfoto-vurdering for topp-lister
7. Score, eksport (CSV, GeoJSON, kart) og rapport
8. Utrulling til alle 18 kommuner og samlet fylkesliste; `python -m odehus.web` lager `docs/data.json`

```bash
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m odehus.pipeline alle
.venv/bin/python -m odehus.fylke
.venv/bin/python -m odehus.web
```

Kjøring krever ingen nøkler eller innlogging. Nedlastede data (`data/`) og resultatfiler (`out/`)
er ikke med i repoet. Datasett og lisenser står i `LICENSES.md`. Ingen persondata lagres: bare
matrikkelnummer, bruksnavn og beregnede verdier. Eierforhold må slås opp manuelt på seeiendom.no.

Rangeringen er en hjelp til å lete, ikke en fasit. Laserproxyen for forfall bommer ofte i lavlandet
(nye hus er yngre enn laserdataene); flyfoto må alltid sjekkes.
