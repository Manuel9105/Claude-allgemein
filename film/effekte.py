#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Effekte: Partikel-Overlays (Staub, Glut, Funken) und Glow-Hintergrund.

Die Overlays sind schwarze Videos mit leuchtenden Punkten.
Sie werden im Film per "screen" übergeblendet. Sie laufen nahtlos in Schleife.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

ARTEN = {
    # n: Anzahl, farbe: RGB, groesse: Radius in px bei 960x540, steigt: Richtung, tempo: Schleifen pro Lauf
    "staub":  dict(n=95, farbe=(255, 214, 150), groesse=(1.6, 6.0), hell=(0.35, 0.95), steigt=True,  schleifen=(1, 2), sway=22, bokeh=14),
    "glut":   dict(n=70, farbe=(255, 125, 45),  groesse=(1.2, 4.5), hell=(0.5, 1.0),   steigt=True,  schleifen=(2, 4), sway=34, bokeh=4),
    "funken": dict(n=80, farbe=(150, 225, 255), groesse=(1.2, 5.0), hell=(0.4, 1.0),   steigt=False, schleifen=(1, 2), sway=40, bokeh=8),
}


def _sprite(radius: float) -> np.ndarray:
    r = int(np.ceil(radius * 3))
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return np.exp(-(x ** 2 + y ** 2) / (2 * radius ** 2)).astype(np.float32)


def partikel(pfad: Path, art: str = "staub", dauer: int = 10, fps: int = 25,
             w: int = 960, h: int = 540, seed: int = 3) -> Path:
    """Rendert die Schleife nach `pfad` (mp4). Gibt den Pfad zurück."""
    cfg = ARTEN[art]
    rng = np.random.default_rng(seed)
    n = cfg["n"] + cfg["bokeh"]
    x0 = rng.uniform(0, w, n)
    y0 = rng.uniform(0, h, n)
    tiefe = rng.uniform(0.35, 1.0, n)
    gross = np.concatenate([
        rng.uniform(*cfg["groesse"], cfg["n"]),
        rng.uniform(16, 38, cfg["bokeh"]),
    ])
    hell = np.concatenate([
        rng.uniform(*cfg["hell"], cfg["n"]),
        rng.uniform(0.05, 0.14, cfg["bokeh"]),
    ])
    k = rng.integers(cfg["schleifen"][0], cfg["schleifen"][1] + 1, n)
    m1 = rng.integers(1, 4, n)
    m2 = rng.integers(2, 7, n)
    ph1 = rng.uniform(0, 2 * np.pi, n)
    ph2 = rng.uniform(0, 2 * np.pi, n)
    farbe = np.array(cfg["farbe"], dtype=np.float32) / 255.0
    sprites = {}

    frames = dauer * fps
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "16",
           "-preset", "fast", "-pix_fmt", "yuv420p", str(pfad)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(frames):
        u = f / frames
        bild = np.zeros((h, w, 3), dtype=np.float32)
        richtung = -1 if cfg["steigt"] else 1
        for i in range(n):
            y = (y0[i] + richtung * k[i] * h * u) % h
            x = (x0[i] + cfg["sway"] * tiefe[i] * np.sin(2 * np.pi * m1[i] * u + ph1[i])) % w
            flackern = 0.65 + 0.35 * np.sin(2 * np.pi * m2[i] * u + ph2[i])
            g = float(gross[i])
            key = round(g * 2) / 2
            sp = sprites.get(key)
            if sp is None:
                sp = sprites[key] = _sprite(key)
            r = sp.shape[0] // 2
            cx, cy = int(x), int(y)
            x1, x2 = max(0, cx - r), min(w, cx + r + 1)
            y1, y2 = max(0, cy - r), min(h, cy + r + 1)
            if x1 >= x2 or y1 >= y2:
                continue
            teil = sp[y1 - (cy - r): y2 - (cy - r), x1 - (cx - r): x2 - (cx - r)]
            bild[y1:y2, x1:x2] += teil[..., None] * farbe * (hell[i] * flackern * (0.5 + 0.5 * tiefe[i]))
        p.stdin.write((np.clip(bild, 0, 1) * 255).astype(np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg konnte das Partikelvideo nicht schreiben")
    return pfad


def glow_bild(pfad: Path, w: int, h: int, farbe=(70, 48, 20)) -> Path:
    """Weiches Zentrum-Leuchten als PPM für Titelkarten-Hintergrund."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    d = ((x - w / 2) ** 2 + ((y - h * 0.48) * 1.3) ** 2) / (2 * (w * 0.32) ** 2)
    g = np.exp(-d)[..., None]
    basis = np.array([6, 9, 20], dtype=np.float32)
    bild = basis + g * np.array(farbe, dtype=np.float32)
    bild = np.clip(bild, 0, 255).astype(np.uint8)
    with open(pfad, "wb") as fh:
        fh.write(f"P6\n{w} {h}\n255\n".encode())
        fh.write(bild.tobytes())
    return pfad


if __name__ == "__main__":
    import sys
    ziel = Path(sys.argv[1] if len(sys.argv) > 1 else "staub.mp4")
    partikel(ziel, sys.argv[2] if len(sys.argv) > 2 else "staub")
    print(ziel)
