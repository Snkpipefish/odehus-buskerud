# Datasett, lisens og nedlastingsdato

| Datasett | Kilde | Lisens | Lastet ned | Fil |
|---|---|---|---|---|
| Matrikkelen – Bygningspunkt (3336 Rollag) | Geonorge/Kartverket, uuid 24d7e9d1-87f6-45a0-b38e-3447f8d7f9a1 | Åpne data (IsOpenData=true i kartkatalogen; CC BY 4.0 / NLOD – verifiser på datasettsiden) | 2026-11-07 (datauttak 2026-11-05) | data/raw/3336/MatrikkelenBygning_GML.zip |
| Matrikkelen – Eiendomskart Teig (3336 Rollag) | Geonorge/Kartverket, uuid 74340c24-1c8a-4454-b813-bfe498e80f16 | Åpne data (IsOpenData=true) | 2026-11-07 (datauttak 2026-10-31) | data/raw/3336/MatrikkelenEiendomskartTeig_GML.zip |
| Matrikkelen – Adresse (3336 Rollag) | Geonorge/Kartverket, uuid f7df7a18-b30f-4745-bd64-d0863812350c | Åpne data (IsOpenData=true) | 2026-11-07 (datauttak 2026-11-05) | data/raw/3336/MatrikkelenAdresse_GML.zip |
| Kommuneliste Buskerud | api.kartverket.no/kommuneinfo/v1 | NLOD | 2026-11-07 | hentes live |

Nedlasting gikk uten innlogging via `https://nedlasting.geonorge.no/geonorge/Basisdata/<Datasett>/GML/Basisdata_<knr>_<Kommune>_25833_<Datasett>_GML.zip`.
| Kodeliste bygningstype | Fra produktskjemaet `skjema.geonorge.no/SOSI/produktspesifikasjon/Matrikkelen-Bygningspunkt/20211101/matrikkelenBygningspunkt.xsd` (BygningstypeKodeEnumerationType, 118 koder) | åpen | 2026-11-07 | src/odehus/kodelister/bygningstype.csv |
| Kodeliste bygningsstatus | register.geonorge.no/sosi-kodelister/fkb/bygning/5.0/bygningsstatus (12 koder) | åpen | 2026-11-07 | src/odehus/kodelister/bygningsstatus.csv |

Merk: Bygningspunkt-produktet utelater selv BR (revet/brent), BA (avlyst), BF (flyttet) og BU (utgått) og inneholder ikke byggeår.
| Nasjonal høydemodell DTM (WCS, 10 m resamplet) | Kartverket, uuid 0f0a0f38-00c4-4213-a9e5-2d861dc4abb0, `wcs.geonorge.no/skwms1/wcs.hoyde-dtm-nhm-25833` (WCS 1.0.0, 20 km-fliser) | CC BY 4.0 (Kartverket høydedata; verifiser på datasettsiden) | 2026-11-07 | data/raw/3336/dtm10/, data/derived/3336/dtm10.tif |
| Terrenghøyde punkt (moh) | Kartverket høyde-API `ws.geonorge.no/hoydedata/v1/punkt` (DTM1) | NLOD/CC BY 4.0 | 2026-11-07 | data/derived/3336/hoyde_cache.json |
| PVGIS 5.2 printhorizon + MRcalc (SARAH2 2016–2020) | EU JRC, `re.jrc.ec.europa.eu/api/v5_2` | Fri bruk med kildehenvisning: «PVGIS © European Union, 2001–2024» | 2026-11-07 | data/derived/3336/pvgis/ |

Merk: Geonorges nedlastbare «DTM 10 Terrengmodell (UTM33)» er nå merket historisk; WCS-tjenesten over er den gjeldende nasjonale høydemodellen.
| Nasjonal høydemodell DOM (WCS, 1 m, per kandidat) | Kartverket, uuid e36ea427-13a1-4d7c-be82-977068dfc3e3, `wcs.geonorge.no/skwms1/wcs.hoyde-dom-nhm-25833` | CC BY 4.0 | 2026-11-07 | data/raw/3336/ndsm/ |
| Arealressurskart AR50 (Rollag-bbox) | NIBIO WFS `wfs.nibio.no/cgi-bin/ar50_2`, uuid a7949917-033c-4e78-8c0f-e30323ce353a | NLOD 1.0 | 2026-11-07 | data/raw/3336/ar50.gml |
| FKB-AR5 punktoppslag (GetFeatureInfo) | NIBIO «Arealressurskart – FKB-AR5 – Forvaltning – 2 – WMS», uuid 7e6307a0-1a7d-4470-a722-a4368faf31e6, `wms.nibio.no/cgi-bin/ar5forvaltning2` | NLOD 2.0 (tjenesten er merket «Åpne data»; selve FKB-AR5-datasettet er Norge digitalt-begrenset og lastes ikke ned) | 2026-11-07 | data/derived/3336/ar5_tun_cache.json |
| NVDB Vegnett (vegsegmenter Rollag) | Statens vegvesen, NVDB API Les v4 `nvdbapiles.atlas.vegvesen.no/vegnett/api/v4` | NLOD | 2026-11-07 | data/raw/3336/nvdb_vegnett.jsonl |

Ikke brukt (krever Norge digitalt / BAAT): FKB-AR5 nedlasting, Dyrkbar jord, alle Norge i bilder-tjenester (WMS/WMTS/prosjekter). Elveg 2.0 finnes ikke lenger; NVDB Vegnett på Geonorge er kun SOSI.
| Ortofoto, visuell vurdering (topp 300 Rollag) | norgeibilder.no (publikumsvisning, nyeste ortofoto) sett i nettleser av Claude; ingen bilder lagret i repoet | Visning tillatt for alle; ingen nedlasting | 2026-11-08 | out/vurder_3336.json |

## Nettside (docs/) – bilder og karttjenester

| Datasett | Kilde | Lisens / vilkår | Dato | Fil |
|---|---|---|---|---|
| Satellittutsnitt per prospekt (512 px, zoom 18, ca. 300 × 300 m) | Esri World Imagery, `server.arcgisonline.com/.../World_Imagery/MapServer/tile` (nøkkelfritt) | Esri Master Agreement / ArcGIS Online basemap-vilkår; attribusjon «Esri, Maxar, Earthstar Geographics, GIS User Community» er brent inn i hvert bilde og vist på siden. Ikke-kommersiell visning. Samme metode som i GULLØYE. | 2026-11-10 | docs/img/*.jpg, data/raw/esri/ (flis-cache, ikke i git) |
| Bakgrunnskart topo / topo grå (WMTS) | Kartverket `cache.kartverket.no/v1/wmts` | CC BY 4.0 | 2026-11-10 | live i nettleser |
| Eiendomsgrenser (WMS) | Kartverket `wms.geonorge.no/skwms1/wms.matrikkelkart`, lag `eiendomsgrense` | CC BY 4.0 / NLOD | 2026-11-10 | live i nettleser |
| Sentinel-2 cloudless 2023 (WMTS) | EOX `tiles.maps.eox.at`, Copernicus Sentinel-2 | CC BY 4.0 (EOX) / Copernicus | 2026-11-10 | live i nettleser |
| Terrengmesh for globus | Re:Earth `terrain.reearth.land/cesium-mesh/ellipsoid` (nøkkelfritt, som i gods-eye-view) | Fri bruk | 2026-11-10 | live i nettleser |
| CesiumJS 1.119 | cdn.jsdelivr.net | Apache 2.0 | 2026-11-10 | lastes i nettleser |
