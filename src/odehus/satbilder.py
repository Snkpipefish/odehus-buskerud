"""Satellittutsnitt per prospekt fra Esri World Imagery (nøkkelfritt, krever attribusjon) – samme metode
som i GULLØYE: 3x3 fliser sys sammen, kvadratisk utsnitt sentrert på tunet, sikte og målestokk tegnes på.

Skriver docs/img/<knr>-<gnr>-<bnr>-<rank>.jpg for alle prospekter i docs/data.json og legger inn
feltet `img` i data.json. Flisene caches i data/raw/esri/.

Kjør: python -m odehus.satbilder [zoom=18] [size=512]
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from . import config as C

TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ATTRIB = "Esri, Maxar, Earthstar Geographics, GIS User Community"
_ses = requests.Session()
import threading
_lås = threading.Lock()
_ses.headers["User-Agent"] = "odehus-buskerud/0.1 (satellittutsnitt; se github.com/Snkpipefish/odehus-buskerud)"


def _font(size=13):
    for name in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def _flis(cache: Path, z: int, x: int, y: int) -> Image.Image:
    f = cache / f"{z}_{x}_{y}.jpg"
    with _lås:  # én tråd per flis: ellers kan en tråd lese en halvskrevet fil
        for forsok in range(5):
            if f.exists() and f.stat().st_size > 500:
                try:
                    return Image.open(f).convert("RGB")
                except Exception:  # noqa: BLE001 - ødelagt/ufullstendig fil, hent på nytt
                    f.unlink(missing_ok=True)
            try:
                r = _ses.get(TILE.format(z=z, x=x, y=y), timeout=30)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") and len(r.content) > 500:
                    Image.open(BytesIO(r.content)).verify()
                    tmp = f.with_suffix(".tmp")
                    tmp.write_bytes(r.content)
                    tmp.replace(f)
                    continue
            except (requests.RequestException, OSError, Image.UnidentifiedImageError):
                pass
            time.sleep(2 * 2 ** forsok)
        raise RuntimeError(f"flis {z}/{x}/{y} feilet")


def crop(cache: Path, lat: float, lon: float, z: int = 18, size: int = 512) -> tuple[Image.Image, float]:
    """Kvadratisk utsnitt sentrert på punktet. Returnerer (bilde, meter per piksel)."""
    fx, fy = _tile_xy(lat, lon, z)
    cx, cy = int(fx), int(fy)
    canvas = Image.new("RGB", (256 * 3, 256 * 3))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            canvas.paste(_flis(cache, z, cx + dx, cy + dy), ((dx + 1) * 256, (dy + 1) * 256))
    px = int((fx - cx + 1) * 256), int((fy - cy + 1) * 256)
    box = (px[0] - size // 2, px[1] - size // 2, px[0] + size // 2, px[1] + size // 2)
    m_per_px = 156543.03 * math.cos(math.radians(lat)) / (2 ** z)
    return canvas.crop(box), m_per_px


def annotate(img: Image.Image, m_per_px: float, title: str = "", sub: str = "") -> Image.Image:
    d = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    c = (w // 2, h // 2)
    col = (255, 230, 0, 255)
    d.ellipse((c[0] - 10, c[1] - 10, c[0] + 10, c[1] + 10), outline=col, width=2)
    for a, b in (((c[0] - 26, c[1]), (c[0] - 12, c[1])), ((c[0] + 12, c[1]), (c[0] + 26, c[1])),
                 ((c[0], c[1] - 26), (c[0], c[1] - 12)), ((c[0], c[1] + 12), (c[0], c[1] + 26))):
        d.line((a, b), fill=col, width=2)
    bar = int(50 / m_per_px)
    d.rectangle((10, h - 16, 10 + bar, h - 12), fill=(255, 255, 255, 255))
    f = _font(13)
    d.text((10, h - 32), "50 m", fill=(255, 255, 255, 255), font=f)
    if title:
        d.rectangle((0, 0, w, 22), fill=(0, 0, 0, 170))
        d.text((6, 4), title, fill=(255, 255, 255, 255), font=f)
    if sub:
        f2 = _font(11)
        d.rectangle((0, h - 14, w, h), fill=(0, 0, 0, 130))
        d.text((w - 6 - d.textlength(sub, font=f2), h - 13), sub, fill=(200, 200, 200, 255), font=f2)
    return img


def main(z: int = 18, size: int = 512, traader: int = 4) -> int:
    cfg = C.load()
    cache = C.ROOT / cfg["paths"]["raw"] / "esri"
    cache.mkdir(parents=True, exist_ok=True)
    ut = C.ROOT / "docs" / "img"
    ut.mkdir(exist_ok=True)
    df = C.ROOT / "docs" / "data.json"
    d = json.loads(df.read_text(encoding="utf-8"))
    t0 = time.time()

    def _en(p):
        navn = f"{p['knr']}-{p['gnr']}-{p['bnr']}-{p['rank']}.jpg"
        f = ut / navn
        if not f.exists():
            img, mpp = crop(cache, p["lat"], p["lon"], z, size)
            tittel = f"#{p['rank']}  {p.get('navn') or ''}  {p['kommune']} {p['gnr']}/{p['bnr']}".strip()
            annotate(img, mpp, tittel, ATTRIB).save(f, quality=80, optimize=True)
            time.sleep(0.05)
        return navn

    rader = d["prospekter"]
    with ThreadPoolExecutor(max_workers=traader) as ex:
        for i, (p, navn) in enumerate(zip(rader, ex.map(_en, rader)), 1):
            p["img"] = "img/" + navn
            if i % 50 == 0:
                print(f"satbilder {i}/{len(rader)} ({time.time() - t0:.0f} s)", flush=True)
    d["meta"]["bilder"] = dict(kilde="Esri World Imagery", attribusjon=ATTRIB, zoom=z, px=size)
    df.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    mb = sum(f.stat().st_size for f in ut.glob("*.jpg")) / 1e6
    print(f"ferdig: {len(rader)} bilder, {mb:.1f} MB, {time.time() - t0:.0f} s")
    return len(rader)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 18, int(a[1]) if len(a) > 1 else 512)
