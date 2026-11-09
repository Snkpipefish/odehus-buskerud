#!/bin/bash
# Venter til pipelinen er ferdig og kjører fylkessamlingen.
# Mønsteret er forankret i starten av kommandolinjen, ellers treffer pgrep skall som bare nevner pipelinen.
cd "/home/pc/prosjekter/forlatte hus"
while pgrep -f "^\.venv/bin/python -m odehus\.pipeline alle" > /dev/null; do sleep 120; done
echo "pipeline ferdig $(date)" >> out/logg_vakt.txt
.venv/bin/python -m odehus.fylke >> out/logg_vakt.txt 2>&1
echo "fylke ferdig $(date)" >> out/logg_vakt.txt
