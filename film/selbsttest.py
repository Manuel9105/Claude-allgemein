#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Selbsttest: baut aus Test-Clips einen Mini-Film und prüft das Ergebnis.

Aufruf: uv run --with numpy python film/selbsttest.py [--behalte ORDNER]
Dauert ein paar Minuten. Beweist, dass Bild, Ton, Effekte und Zusammenbau laufen.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kino  # noqa: E402


def ff(*a):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, a)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[-1500:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--behalte", help="Ordner, in dem das Ergebnis bleibt")
    a = ap.parse_args()
    wurzel = Path(a.behalte) if a.behalte else Path(tempfile.mkdtemp(prefix="kino_test_"))
    sz, ar, au = wurzel / "szenen", wurzel / "arbeit", wurzel / "ausgabe"
    for d in (sz, ar, au):
        d.mkdir(parents=True, exist_ok=True)

    # Drei Test-Szenen: quer mit Ton, hochkant mit Knall, ohne Ton
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4", "-f", "lavfi", "-i",
       "aevalsrc='0.3*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*3*t))':d=4:s=48000", "-c:v", "libx264", "-c:a", "aac", sz / "01_quer.mp4")
    ff("-f", "lavfi", "-i", "testsrc2=s=360x640:r=25:d=4", "-f", "lavfi", "-i",
       "aevalsrc='0.02*random(0)+if(between(t,2,2.08),0.9*sin(2*PI*90*t),0)':d=4:s=48000", "-c:v", "libx264", "-c:a", "aac", sz / "02_hochkant.mp4")
    ff("-f", "lavfi", "-i", "rgbtestsrc=s=640x360:r=25:d=3", "-c:v", "libx264", sz / "03_stumm.mp4")

    regie = {
        "titel": "DIE TESTBANDE\nUND DER SCHATZ", "untertitel": "Ein Selbsttest", "look": "auto", "format": "kino",
        "vorspann": True, "abspann": {"zeilen": ["# Regie", "Die Testbande", "", "Musik: original komponiert"]},
        "musik_lautstaerke": 0.55, "sfx_lautstaerke": 0.7,
        "szenen": [
            {"datei": "01_quer.mp4", "kapitel": "Kapitel 1 – Aufbruch", "stimmung": "abenteuer",
             "zeitlupe": {"von": 1.0, "bis": 2.0, "faktor": 0.5}, "sfx": [{"bei": 1.0, "art": "whoosh_lang"}]},
            {"datei": "02_hochkant.mp4", "kapitel": "Kapitel 2 – Gefahr", "stimmung": "action",
             "wackeln": [{"bei": 2.0, "dauer": 0.6, "staerke": 1.2}], "blitz": [2.0], "sfx": [{"bei": 2.0, "art": "boom"}],
             "uebergang": "zoomin"},
            {"datei": "03_stumm.mp4", "stimmung": "sieg", "von": 0.2, "bis": 2.8, "uebergang": "circleopen",
             "sfx": [{"bei": 0.8, "art": "fanfare"}]},
        ],
    }
    (wurzel / "regie.json").write_text(json.dumps(regie, ensure_ascii=False, indent=2), encoding="utf-8")

    kino.main(["--szenen", str(sz), "--arbeit", str(ar), "--ausgabe", str(au), "--regie", str(wurzel / "regie.json"),
               "--musik", str(wurzel / "musik"), "bauen", "--vorschau"])

    film = sorted(au.glob("*.mp4"))[-1]
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", film],
                                  capture_output=True, text=True).stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    t = next(s for s in d["streams"] if s["codec_type"] == "audio")
    dauer = float(d["format"]["duration"])
    fehler = []
    if (v["width"], v["height"]) != (1280, 720):
        fehler.append(f"Größe {v['width']}x{v['height']}")
    if not 15 < dauer < 40:
        fehler.append(f"Dauer {dauer}")
    if t["codec_name"] != "aac":
        fehler.append("Ton fehlt")
    lau = subprocess.run(["ffmpeg", "-nostats", "-i", film, "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    i_wert = float(lau.split("I:")[-1].split("LUFS")[0])
    if not -19 < i_wert < -13:
        fehler.append(f"Lautheit {i_wert} LUFS")
    print(f"\nFilm: {film}\nDauer {dauer:.1f} s, Lautheit {i_wert:.1f} LUFS")
    if fehler:
        print("SELBSTTEST FEHLGESCHLAGEN:", "; ".join(fehler))
        return 1
    print("SELBSTTEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
