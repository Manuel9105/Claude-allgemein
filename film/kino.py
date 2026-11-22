#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kino-Pipeline für Kinderfilme im Abenteuer-Stil.

Arbeitsteilung (wie bei der Post-Pipeline):
  Das Skript macht die sicheren, prüfbaren Handgriffe (messen, rendern, mischen).
  Das Urteil (Stimmung, Kapitel, Effekte pro Szene) macht Claude.
  Claude schreibt das Urteil in regie.json. Das Skript baut daraus den Film.

Garantien:
  - Originale in szenen/ werden nie verändert, verschoben oder gelöscht.
  - Ausgaben überschreiben nie etwas. Jede Version bekommt eine neue Nummer.
  - Alles Zwischenmaterial liegt in arbeit/ und darf jederzeit gelöscht werden.
  - Musik und Effekte sind original erzeugt (klang.py). Keine fremden Rechte.

Aufruf:  uv run --with numpy python film/kino.py <befehl>
Befehle: status, analyse, bauen, auto, klang
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import effekte  # noqa: E402
import klang  # noqa: E402

VERSION = "3"
ENDUNGEN = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts", ".mpg", ".mpeg"}
STIMMUNGEN = list(klang.STIMMUNGEN)
UEBERGAENGE = {"fade", "fadeblack", "fadewhite", "dissolve", "circleopen", "circleclose", "radial",
               "zoomin", "slideleft", "slideright", "smoothleft", "smoothright", "wipeleft",
               "wiperight", "pixelize", "horzopen", "vertopen"}
QUALITAET = {
    "vorschau": dict(name="vorschau", w=1280, h=720, crf=23, preset="veryfast", z_crf=20, z_preset="veryfast"),
    "final": dict(name="final", w=1920, h=1080, crf=16, preset="slow", z_crf=12, z_preset="fast"),
}


class P:
    """Ordner. Lassen sich für Tests umbiegen."""
    szenen = HIER / "szenen"
    arbeit = HIER / "arbeit"
    ausgabe = HIER / "ausgabe"
    musik = HIER / "musik"
    regie = HIER / "regie.json"
    entwurf = HIER / "regie_entwurf.json"


# ---------------------------------------------------------------- Helfer
def run(cmd: list, was: str = "") -> subprocess.CompletedProcess:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"FEHLER ({was or cmd[0]}):\n{r.stderr[-2200:]}")
    return r


def stil() -> dict:
    return json.loads((HIER / "stil.json").read_text(encoding="utf-8"))


def natuerlich(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def szenen_dateien() -> list[Path]:
    if not P.szenen.exists():
        return []
    fs = [f for f in P.szenen.iterdir() if f.is_file() and f.suffix.lower() in ENDUNGEN and not f.name.startswith(".")]
    return sorted(fs, key=lambda f: natuerlich(f.name))


def probe(pfad: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", pfad], "ffprobe")
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise SystemExit(f"Kein Bild in {pfad.name}")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    rot = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    rot = abs(rot or int(v.get("tags", {}).get("rotate", 0) or 0)) % 180
    w, h = int(v["width"]), int(v["height"])
    if rot == 90:
        w, h = h, w
    n, _, dn = (v.get("r_frame_rate") or "25/1").partition("/")
    fps = float(n) / float(dn or 1) if float(dn or 1) else 25.0
    dauer = float(d["format"].get("duration") or v.get("duration") or 0)
    return dict(dauer=dauer, w=w, h=h, fps=fps, audio=a is not None)


def schrift() -> str | None:
    s = stil()
    for muster in s["titel"].get("schrift_suche", []):
        treffer = sorted(glob.glob(str(HIER / muster)))
        if treffer:
            return treffer[0]
    for pfad in [
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/Library/Fonts/Arial Black.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if Path(pfad).exists():
            return pfad
    return None


def ff_text(pfad: Path) -> str:
    """Pfad für ffmpeg-Filteroptionen absichern."""
    return str(pfad).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def font_opt() -> str:
    f = schrift()
    return f"fontfile='{ff_text(Path(f))}':" if f else "font=Sans:"


def sek(x: float) -> str:
    return f"{x:.3f}"


# ---------------------------------------------------------------- Messen
def messen(pfad: Path, info: dict) -> dict:
    """Misst Helligkeit, Bewegung, Lautstärke, Stille und Knalle einer Szene."""
    r = run(["ffmpeg", "-v", "error", "-i", pfad, "-an", "-vf",
             "fps=4,scale=320:-2,signalstats,select='gte(scene,0)',metadata=print:file=-",
             "-f", "null", "-"], "Bildmessung")
    yavg, sat, scene = [], [], []
    for z in r.stdout.splitlines():
        if z.startswith("lavfi.signalstats.YAVG="):
            yavg.append(float(z.split("=")[1]))
        elif z.startswith("lavfi.signalstats.SATAVG="):
            sat.append(float(z.split("=")[1]))
        elif z.startswith("lavfi.scene_score="):
            scene.append(float(z.split("=")[1]))
    m = dict(helligkeit=float(np.mean(yavg)) if yavg else 100.0,
             farbe=float(np.mean(sat)) if sat else 40.0,
             bewegung=float(np.mean(scene[1:])) if len(scene) > 1 else 0.0,
             lautstaerke=None, stille=0.0, stoesse=[])
    if info["audio"]:
        r = run(["ffmpeg", "-v", "info", "-nostats", "-i", pfad, "-vn", "-af",
                 "silencedetect=n=-38dB:d=0.5,volumedetect", "-f", "null", "-"], "Tonmessung")
        mm = re.search(r"mean_volume:\s*(-?[\d.]+)", r.stderr)
        if mm:
            m["lautstaerke"] = float(mm.group(1))
        stille = sum(float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", r.stderr))
        m["stille"] = min(1.0, stille / max(info["dauer"], 0.1))
        m["stoesse"] = stoesse(pfad)
    return m


def stoesse(pfad: Path) -> list[float]:
    """Findet laute Knalle: Spitze springt weit über den Ton davor."""
    r = run(["ffmpeg", "-v", "error", "-i", pfad, "-vn", "-af",
             "aresample=22050,asetnsamples=n=1102:p=0,astats=metadata=1:reset=1,"
             "ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-", "-f", "null", "-"], "Stoßsuche")
    zeiten, spitzen = [], []
    t = 0.0
    for z in r.stdout.splitlines():
        mt = re.search(r"pts_time:([\d.]+)", z)
        if mt:
            t = float(mt.group(1))
        elif "Peak_level=" in z:
            v = z.split("=")[1]
            spitzen.append(-90.0 if "inf" in v else float(v))
            zeiten.append(t)
    treffer: list[float] = []
    for i in range(20, len(spitzen)):
        basis = float(np.median(spitzen[i - 20:i]))
        if spitzen[i] - basis > 16 and spitzen[i] > -10 and (not treffer or zeiten[i] - treffer[-1] > 2.0):
            treffer.append(round(zeiten[i], 2))
    return treffer[:3]


def stimmung_raten(m: dict) -> str:
    if m["helligkeit"] < 70:
        return "spannung"
    laut = m["lautstaerke"] if m["lautstaerke"] is not None else -40
    if m["bewegung"] > 0.08 and laut > -24:
        return "action"
    if m["bewegung"] > 0.03:
        return "abenteuer"
    return "ruhig"


def kontaktbogen(pfad: Path, dauer: float, ziel: Path) -> None:
    rate = 6 / max(dauer, 0.5)
    run(["ffmpeg", "-y", "-v", "error", "-i", pfad, "-an", "-vf",
         f"fps={rate:.4f},scale=320:-2,tile=6x1", "-frames:v", "1", "-q:v", "4", ziel], "Kontaktbogen")


def analyse(_args=None) -> dict:
    fs = szenen_dateien()
    if not fs:
        raise SystemExit(f"Keine Szenen in {P.szenen}. Zieh deine Clips dort hinein (mp4, mov ...).")
    P.arbeit.mkdir(parents=True, exist_ok=True)
    s = stil()
    szenen, rows = [], []
    for i, f in enumerate(fs, 1):
        info = probe(f)
        m = messen(f, info)
        st = stimmung_raten(m)
        kontaktbogen(f, info["dauer"], P.arbeit / f"kontakt_{i:02d}.jpg")
        sz = {"datei": f.name, "kapitel": "", "stimmung": st, "originalton": 1.0}
        if st == "action" and m["stoesse"]:
            sz["wackeln"] = [{"bei": t, "dauer": 0.5, "staerke": 1.0} for t in m["stoesse"]]
            sz["blitz"] = m["stoesse"][:1]
        szenen.append(sz)
        rows.append((i, f.name, info, m, st))
    entwurf = {
        "titel": "MEIN FILM",
        "untertitel": "",
        "look": "auto",
        "format": "kino",
        "vorspann": True,
        "abspann": {"zeilen": ["# Ein Film von", "Euch allen", "", "# Musik", "Original komponiert"]},
        "musik_lautstaerke": 0.55,
        "sfx_lautstaerke": 0.7,
        "szenen": szenen,
    }
    P.entwurf.write_text(json.dumps(entwurf, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{'Nr':>2}  {'Datei':<28} {'Dauer':>6} {'Format':>9} {'hell':>5} {'Bew.':>5} {'dB':>6}  Stimmung")
    for i, name, info, m, st in rows:
        db = f"{m['lautstaerke']:.0f}" if m["lautstaerke"] is not None else "-"
        print(f"{i:>2}  {name[:28]:<28} {info['dauer']:>5.1f}s {info['w']}x{info['h']:<4} {m['helligkeit']:>5.0f} {m['bewegung']:>5.2f} {db:>6}  {st}")
    print(f"\nEntwurf: {P.entwurf}\nKontaktbögen: {P.arbeit}/kontakt_NN.jpg")
    _ = s
    return entwurf


# ---------------------------------------------------------------- Regie
def regie_laden() -> dict:
    pfad = P.regie if P.regie.exists() else P.entwurf
    if not pfad.exists():
        raise SystemExit("Keine Regie da. Erst `analyse` laufen lassen.")
    return json.loads(pfad.read_text(encoding="utf-8"))


def stimmung_von(sz: dict) -> str:
    st = sz.get("stimmung", "abenteuer")
    if st not in STIMMUNGEN:
        raise SystemExit(f"Unbekannte Stimmung '{st}'. Erlaubt: {', '.join(STIMMUNGEN)}")
    return st


def look_von(regie: dict, sz: dict, s: dict) -> dict:
    name = sz.get("look")
    if not name:
        name = regie.get("look", "auto")
        if name in (None, "auto"):
            name = s["stimmungen"][stimmung_von(sz)]["look"]
    if name not in s["looks"]:
        raise SystemExit(f"Unbekannter Look '{name}'. Erlaubt: {', '.join(s['looks'])}")
    return s["looks"][name]


def partikel_datei(art: str, fps: int) -> Path:
    P.arbeit.mkdir(parents=True, exist_ok=True)
    pfad = P.arbeit / f"partikel_{art}_{fps}.mp4"
    if not pfad.exists():
        effekte.partikel(pfad, art, fps=fps)
    return pfad


# ---------------------------------------------------------------- Filtergraph-Baukasten
class Graph:
    def __init__(self, start: str):
        self.teile: list[str] = []
        self.cur = start
        self.n = 0

    def lin(self, f: str) -> None:
        self.n += 1
        out = f"g{self.n}"
        self.teile.append(f"[{self.cur}]{f}[{out}]")
        self.cur = out

    def roh(self, text: str, neu: str) -> None:
        self.teile.append(text)
        self.cur = neu

    def text(self) -> str:
        return ";".join(self.teile)


def atempo(f: float) -> str:
    t = []
    while f < 0.5:
        t.append("atempo=0.5")
        f /= 0.5
    t.append(f"atempo={f:.4f}")
    return ",".join(t)


def schnitt_dauer(sz: dict, info: dict, fps: int) -> tuple[float, float, float, dict | None]:
    von = float(sz.get("von", 0) or 0)
    bis = float(sz.get("bis") or info["dauer"])
    bis = min(bis, info["dauer"])
    quell = max(0.2, bis - von)
    zl = sz.get("zeitlupe")
    ausgabe = quell
    if zl:
        zv = max(0.0, float(zl["von"]))
        zb = min(quell, float(zl["bis"]))
        f = min(1.0, max(0.2, float(zl.get("faktor", 0.5))))
        zl = dict(von=zv, bis=zb, faktor=f)
        ausgabe = quell + (zb - zv) * (1 / f - 1)
    ausgabe = round(ausgabe * fps) / fps
    return von, quell, ausgabe, zl


# ---------------------------------------------------------------- Szene rendern
def szene_rendern(sz: dict, regie: dict, q: dict, s: dict) -> tuple[Path, float]:
    quelle = P.szenen / sz["datei"]
    if not quelle.exists():
        raise SystemExit(f"Szene fehlt: {quelle}")
    info = probe(quelle)
    fps = int(s["fps"])
    W, H = q["w"], q["h"]
    stim = stimmung_von(sz)
    sst = s["stimmungen"][stim]
    look = look_von(regie, sz, s)
    von, quell, D, zl = schnitt_dauer(sz, info, fps)

    schluessel = hashlib.sha1(json.dumps(
        [VERSION, sz, q["name"], look, sst, fps, quelle.stat().st_size, int(quelle.stat().st_mtime)],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    P.arbeit.mkdir(parents=True, exist_ok=True)
    ziel = P.arbeit / f"szene_{Path(sz['datei']).stem}_{q['name']}_{schluessel}.mkv"
    if ziel.exists():
        return ziel, probe(ziel)["dauer"]

    g: list[str] = []
    # ---- Bild-Basis (Hochkant & Co.: unscharfer Rand statt schwarzer Balken)
    if abs((info["w"] / info["h"]) / (W / H) - 1) > 0.02:
        g.append(f"[0:v]fps={fps},setpts=PTS-STARTPTS,setsar=1,split=2[bgi][fgi]")
        g.append(f"[bgi]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=30,eq=brightness=-0.08:saturation=0.9[bgo]")
        g.append(f"[fgi]scale={W}:{H}:force_original_aspect_ratio=decrease[fgo]")
        g.append("[bgo][fgo]overlay=(W-w)/2:(H-h)/2,setsar=1[v0]")
    else:
        g.append(f"[0:v]fps={fps},setpts=PTS-STARTPTS,scale={W}:{H},setsar=1[v0]")
    if info["audio"]:
        g.append("[0:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a0]")
    else:
        g.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{sek(quell)},asetpts=PTS-STARTPTS[a0]")

    # ---- Zeitlupe (Bild + Ton gemeinsam)
    vcur, acur = "v0", "a0"
    if zl:
        teile = []
        if zl["von"] > 0.04:
            teile.append((0.0, zl["von"], 1.0))
        teile.append((zl["von"], zl["bis"], zl["faktor"]))
        if quell - zl["bis"] > 0.04:
            teile.append((zl["bis"], quell, 1.0))
        n = len(teile)
        g.append(f"[{vcur}]split={n}" + "".join(f"[vz{i}]" for i in range(n)))
        g.append(f"[{acur}]asplit={n}" + "".join(f"[az{i}]" for i in range(n)))
        for i, (a, b, f) in enumerate(teile):
            if f < 1.0:
                g.append(f"[vz{i}]trim=start={sek(a)}:end={sek(b)},setpts=(PTS-STARTPTS)/{f},minterpolate=fps={fps}:mi_mode=blend[vp{i}]")
                g.append(f"[az{i}]atrim=start={sek(a)}:end={sek(b)},asetpts=PTS-STARTPTS,{atempo(f)},lowpass=f=2600,volume=0.7[ap{i}]")
            else:
                g.append(f"[vz{i}]trim=start={sek(a)}:end={sek(b)},setpts=PTS-STARTPTS[vp{i}]")
                g.append(f"[az{i}]atrim=start={sek(a)}:end={sek(b)},asetpts=PTS-STARTPTS[ap{i}]")
        g.append("".join(f"[vp{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vz]")
        g.append("".join(f"[ap{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[az]")
        vcur, acur = "vz", "az"

    # ---- Ton
    ton = float(sz.get("originalton", 1.0))
    g.append(f"[{acur}]highpass=f=70,afftdn=nr=10:nf=-28,acompressor=threshold=0.08:ratio=3:attack=10:release=250:makeup=2,"
             f"equalizer=f=3200:t=q:w=1:g=2,dynaudnorm=f=250:g=15:m=5,volume={ton:.2f},"
             f"apad=whole_dur={sek(D)},atrim=0:{sek(D)}[aout]")

    # ---- Bild-Effekte
    gr = Graph(vcur)
    bew = sz.get("bewegung", sst["bewegung"])
    zoom = float(sz.get("zoom", sst["zoom"]))
    if bew in ("push", "pull") and zoom > 0:
        ze = f"(1+{zoom}*t/{D:.3f})" if bew == "push" else f"(1+{zoom}*(1-t/{D:.3f}))"
        gr.lin(f"scale=w='trunc({W}*{ze}/2)*2':h='trunc({H}*{ze}/2)*2':eval=frame:flags=bilinear,crop={W}:{H}")
    wack = sz.get("wackeln") or []
    if wack:
        amp = max(float(w.get("staerke", 1.0)) for w in wack) * W * 0.008
        mx, my = int(math.ceil(amp)) + 2, int(math.ceil(amp * H / W)) + 2
        ex, ey = [], []
        for w in wack:
            b, d, k = float(w["bei"]), float(w.get("dauer", 0.5)), float(w.get("staerke", 1.0)) * W * 0.008
            gate = f"between(t,{b},{b + d})*(1-(t-{b})/{d})"
            ex.append(f"{k:.2f}*sin(t*61)*{gate}")
            ey.append(f"{k * H / W:.2f}*sin(t*47+1)*{gate}")
        gr.lin(f"crop=w={W - 2 * mx}:h={H - 2 * my}:x='{mx}+{'+'.join(ex)}':y='{my}+{'+'.join(ey)}',scale={W}:{H}")
    if look.get("cartoon"):
        # Comic-Look: Farben glätten, nur die Helligkeit in Stufen, dünne dunkle Konturen darüber
        stufe = int(256 / max(3, int(look.get("stufen", 8))))
        gr.lin("format=yuv420p,median=radius=2,bilateral=sigmaS=4:sigmaR=0.08,gblur=sigma=0.8")
        gr.lin(f"lutyuv=y='trunc(val/{stufe})*{stufe}+{stufe // 2}'")
        gr.n += 1
        n0 = gr.n
        k = float(look.get("kontur", 0.1))
        gr.teile.append(f"[{gr.cur}]split=2[cm{n0}][ce{n0}]")
        gr.teile.append(f"[ce{n0}]format=gray,gblur=sigma=1.4,edgedetect=low={k}:high={k * 3:.3f},negate,format=gbrp[cl{n0}]")
        gr.teile.append(f"[cm{n0}]format=gbrp[cp{n0}]")
        gr.n += 1
        gr.teile.append(f"[cp{n0}][cl{n0}]blend=all_mode=multiply:all_opacity=0.9[g{gr.n}]")
        gr.cur = f"g{gr.n}"
        gr.lin("format=yuv420p")
    gr.lin(f"eq={look['eq']}")
    gr.lin(f"curves=all='{look['curves']}'")
    gr.lin(f"colorbalance={look['colorbalance']}")
    if look.get("bloom", 0) > 0:
        gr.lin("format=gbrp")  # Überblenden nur in RGB, sonst kippen die Farben
        a, b, c = gr.cur, f"bl{gr.n}b", f"bl{gr.n}c"
        gr.teile.append(f"[{a}]split=2[bl{gr.n}a][{b}]")
        gr.teile.append(f"[{b}]curves=all='0/0 0.6/0 0.85/0.55 1/1',gblur=sigma={W * 0.012:.1f}[{c}]")
        gr.n += 1
        out = f"g{gr.n}"
        gr.teile.append(f"[bl{gr.n - 1}a][{c}]blend=all_mode=screen:all_opacity={look['bloom']}[{out}]")
        gr.cur = out
        gr.lin("format=yuv420p")
    blitze = sz.get("blitz") or []
    if blitze:
        ausdruck = "+".join(f"0.8*exp(-11*(t-{float(b)}))*gte(t,{float(b)})" for b in blitze)
        gr.lin(f"eq=brightness='min(0.9,{ausdruck})':eval=frame")
    pk = sz.get("partikel", sst["partikel"])
    eingaben = ["-ss", sek(von), "-t", sek(quell), "-i", quelle]
    if pk and pk != "aus":
        pf = partikel_datei(pk, fps)
        eingaben += ["-stream_loop", "-1", "-i", pf]
        gr.teile.append(f"[1:v]scale={W}:{H}:flags=bilinear,format=gbrp,setsar=1[du]")
        gr.lin("format=gbrp")
        c = gr.cur
        gr.n += 1
        out = f"g{gr.n}"
        gr.teile.append(f"[{c}][du]blend=all_mode=screen:all_opacity=0.9:shortest=1[{out}]")
        gr.cur = out
        gr.lin("format=yuv420p")
    if not look.get("cartoon"):
        gr.lin("unsharp=5:5:0.5:5:5:0.0")
    gr.lin(f"vignette=angle={look['vignette']}")
    if look.get("korn"):
        gr.lin(f"noise=alls={look['korn']}:allf=t+u")
    gr.lin("format=yuv420p")
    g.append(gr.text())

    cmd = ["ffmpeg", "-y", "-v", "error", *eingaben, "-filter_complex", ";".join(g),
           "-map", f"[{gr.cur}]", "-map", "[aout]", "-t", sek(D),
           "-c:v", "libx264", "-crf", q["z_crf"], "-preset", q["z_preset"], "-pix_fmt", "yuv420p", "-r", fps,
           "-c:a", "pcm_s16le", "-ar", 48000, "-ac", 2, ziel]
    run(cmd, f"Szene {sz['datei']}")
    return ziel, probe(ziel)["dauer"]


# ---------------------------------------------------------------- Karten (Vorspann, Abspann)
def _karte_basis(W: int, H: int, fps: int, D: float, pk: str, ppm: Path):
    eing = ["-loop", "1", "-framerate", fps, "-t", sek(D), "-i", ppm,
            "-stream_loop", "-1", "-i", partikel_datei(pk, fps),
            "-f", "lavfi", "-t", sek(D), "-i", "anullsrc=r=48000:cl=stereo"]
    g = [f"[0:v]scale={W}:{H},format=gbrp,setsar=1[bg]",
         f"[1:v]scale={W}:{H}:flags=bilinear,format=gbrp,setsar=1[du]",
         "[bg][du]blend=all_mode=screen:all_opacity=0.9:shortest=1,format=yuv420p[b0]"]
    return eing, g


def _karte_ausgabe(eing, g, cur, q, fps, D, ziel):
    cmd = ["ffmpeg", "-y", "-v", "error", *eing, "-filter_complex", ";".join(g),
           "-map", f"[{cur}]", "-map", "2:a", "-t", sek(D),
           "-c:v", "libx264", "-crf", q["z_crf"], "-preset", q["z_preset"], "-pix_fmt", "yuv420p", "-r", fps,
           "-c:a", "pcm_s16le", "-ar", 48000, "-ac", 2, ziel]
    run(cmd, f"Karte {ziel.name}")


def titelkarte(regie: dict, q: dict, s: dict) -> tuple[Path, float, dict]:
    W, H, fps = q["w"], q["h"], int(s["fps"])
    D, T0 = 6.4, 2.5  # Knall und Titel bei 2,5 s
    schluessel = hashlib.sha1(json.dumps([VERSION, regie.get("titel"), regie.get("untertitel"), q["name"], s["titel"]],
                                         ensure_ascii=False).encode()).hexdigest()[:10]
    P.arbeit.mkdir(parents=True, exist_ok=True)
    ziel = P.arbeit / f"karte_titel_{q['name']}_{schluessel}.mkv"
    meta = dict(stimmung="intro", sfx=[("riser", 0.0, 0.8, T0), ("stinger", T0, 0.95, None)], kapitel="")
    if ziel.exists():
        return ziel, D, meta
    ppm = effekte.glow_bild(P.arbeit / f"glow_{W}x{H}.ppm", W, H)
    eing, g = _karte_basis(W, H, fps, D, "staub", ppm)
    zeilen = [z for z in str(regie.get("titel", "")).split("\n") if z.strip()]
    lang = max((len(z) for z in zeilen), default=8)
    gr_ = min(s["titel"]["groesse"] * H, 0.88 * W / (max(lang, 6) * 0.62))
    ti = s["titel"]
    a = f"min(1,max(0,(t-{T0})/0.35))"
    gr = Graph("b0")
    zh = gr_ * 1.12
    y0 = f"(h-{zh * len(zeilen):.0f})/2-{H * 0.03:.0f}"
    for i, z in enumerate(zeilen):
        tf = P.arbeit / f"titel_{i:02d}.txt"
        tf.write_text(z, encoding="utf-8")
        gr.lin(f"drawtext={font_opt()}textfile='{ff_text(tf)}':fontsize='{gr_:.1f}*(0.88+0.12*min(1,(t-{T0})/2.2))':"
               f"fontcolor={ti['farbe']}:borderw={max(2, int(H * 0.007))}:bordercolor={ti['rand']}:"
               f"shadowx={int(H * 0.008)}:shadowy={int(H * 0.011)}:shadowcolor=black@0.75:"
               f"x=(w-text_w)/2:y={y0}+{i * zh:.0f}:alpha='{a}'")
    if regie.get("untertitel"):
        sf = P.arbeit / "untertitel.txt"
        sf.write_text(str(regie["untertitel"]), encoding="utf-8")
        gr.lin(f"drawtext={font_opt()}textfile='{ff_text(sf)}':fontsize={H * 0.045:.0f}:fontcolor=white@0.92:"
               f"x=(w-text_w)/2:y=(h/2)+{H * 0.2:.0f}:alpha='min(1,max(0,(t-{T0 + 0.9})/0.6))'")
    gr.lin(f"eq=brightness='min(0.9,0.9*exp(-9*(t-{T0}))*gte(t,{T0}))':eval=frame")
    gr.lin(f"fade=t=out:st={D - 0.7}:d=0.7,format=yuv420p")
    g.append(gr.text())
    _karte_ausgabe(eing, g, gr.cur, q, fps, D, ziel)
    return ziel, D, meta


def abspannkarte(regie: dict, q: dict, s: dict) -> tuple[Path, float, dict]:
    W, H, fps = q["w"], q["h"], int(s["fps"])
    zeilen = (regie.get("abspann") or {}).get("zeilen") or []
    zeilen = list(zeilen) + ["", "", "ENDE"]
    lh = H * 0.075
    tempo = H * 0.085
    D = max(7.0, round((H * 0.9 + len(zeilen) * lh) / tempo, 1))
    schluessel = hashlib.sha1(json.dumps([VERSION, zeilen, q["name"], s["titel"]], ensure_ascii=False).encode()).hexdigest()[:10]
    ziel = P.arbeit / f"karte_abspann_{q['name']}_{schluessel}.mkv"
    meta = dict(stimmung="abspann", sfx=[], kapitel="")
    if ziel.exists():
        return ziel, D, meta
    ppm = effekte.glow_bild(P.arbeit / f"glow_{W}x{H}.ppm", W, H, farbe=(40, 28, 12))
    eing, g = _karte_basis(W, H, fps, D, "staub", ppm)
    gr = Graph("b0")
    ti = s["titel"]
    for i, z in enumerate(zeilen):
        if not z.strip():
            continue
        kopf = z.startswith("# ")
        txt = z[2:] if kopf else z
        if z == "ENDE":
            kopf, txt = True, "ENDE"
        zf = P.arbeit / f"abspann_{i:02d}.txt"
        zf.write_text(txt, encoding="utf-8")
        farbe = ti["farbe"] if kopf else "white@0.92"
        gross = H * (0.062 if z == "ENDE" else 0.05 if kopf else 0.042)
        y = f"{H * 1.02:.0f}+{i * lh:.0f}-t*{tempo:.1f}"
        if z == "ENDE":
            y = f"max((h-text_h)/2,{H * 1.02:.0f}+{i * lh:.0f}-t*{tempo:.1f})"
        gr.lin(f"drawtext={font_opt()}textfile='{ff_text(zf)}':fontsize={gross:.0f}:fontcolor={farbe}:"
               f"borderw={2 if kopf else 1}:bordercolor=black@0.7:x=(w-text_w)/2:y='{y}'")
    gr.lin(f"fade=t=in:st=0:d=0.6,fade=t=out:st={D - 1.0}:d=1.0,format=yuv420p")
    g.append(gr.text())
    _karte_ausgabe(eing, g, gr.cur, q, fps, D, ziel)
    return ziel, D, meta


# ---------------------------------------------------------------- Zusammenbau
def uebergang_wahl(regie_sz: dict, s: dict, idx: int) -> tuple[str, float]:
    stim = stimmung_von(regie_sz) if regie_sz.get("datei") else "intro"
    wahl = regie_sz.get("uebergang")
    if not wahl:
        liste = s["stimmungen"][stim]["uebergang"]
        wahl = liste[idx % len(liste)]
    if wahl == "schnitt":
        return "fade", 0.04
    if wahl not in UEBERGAENGE:
        raise SystemExit(f"Unbekannter Übergang '{wahl}'. Erlaubt: {', '.join(sorted(UEBERGAENGE))}, schnitt")
    std = {"action": 0.4}.get(stim, 0.8 if wahl in ("fade", "dissolve", "fadeblack", "fadewhite") else 0.6)
    return wahl, float(regie_sz.get("uebergang_dauer", std))


def musik_stueck(stimmung: str, dauer: float) -> np.ndarray:
    for ext in ("wav", "mp3", "m4a", "flac", "aac", "ogg"):
        eigene = P.musik / f"{stimmung}.{ext}"
        if eigene.exists():
            return klang.auf_laenge(klang.lade_audio(eigene), dauer)
    return klang.komponieren(stimmung, dauer, seed=11)


def bauen(args) -> Path:
    s = stil()
    regie = regie_laden()
    q = QUALITAET["vorschau" if args.vorschau else "final"]
    fps = int(s["fps"])
    W, H = q["w"], q["h"]
    P.arbeit.mkdir(parents=True, exist_ok=True)
    P.ausgabe.mkdir(parents=True, exist_ok=True)

    szs = regie["szenen"]
    if args.nur:
        wahl = {int(x) for x in args.nur.split(",")}
        szs = [z for i, z in enumerate(szs, 1) if i in wahl]
    if not szs:
        raise SystemExit("Keine Szenen in der Regie.")

    clips = []  # (pfad, dauer, szene_oder_None, meta)
    mit_karten = not args.nur
    if mit_karten and regie.get("vorspann", True):
        p, d, meta = titelkarte(regie, q, s)
        clips.append((p, d, {"datei": None, "stimmung": "intro"}, meta))
    for i, sz in enumerate(szs, 1):
        print(f"Szene {i}/{len(szs)}: {sz['datei']} ({stimmung_von(sz)}) ...", flush=True)
        p, d = szene_rendern(sz, regie, q, s)
        clips.append((p, d, sz, dict(stimmung=sz.get("musik") or stimmung_von(sz), sfx=[], kapitel=sz.get("kapitel", ""))))
    if mit_karten and regie.get("abspann", True) is not False:
        p, d, meta = abspannkarte(regie, q, s)
        clips.append((p, d, {"datei": None, "stimmung": "abspann"}, meta))

    # ---- Zeitachse
    starts, tds, tnames = [0.0], [], []
    for i in range(1, len(clips)):
        name, td = uebergang_wahl(clips[i][2], s, i)
        td = max(0.04, min(td, 0.45 * min(clips[i - 1][1], clips[i][1])))
        tds.append(td)
        tnames.append(name)
        starts.append(starts[-1] + clips[i - 1][1] - td)
    gesamt = starts[-1] + clips[-1][1]
    print(f"Gesamtlänge: {gesamt:.1f} s ({len(clips)} Clips)", flush=True)

    # ---- Musik und Effekte (original, numpy)
    sr = klang.SR
    n = int((gesamt + 3) * sr)
    musik = np.zeros((2, n), dtype=np.float32)
    fx = np.zeros((2, n), dtype=np.float32)
    seg: list[list] = []
    for i, c in enumerate(clips):
        m = c[3]["stimmung"]
        if m == "stumm":
            continue
        a, b = starts[i], starts[i] + c[1]
        if seg and seg[-1][2] == m and abs(seg[-1][1] - a) < 3.0:
            seg[-1][1] = b
        else:
            seg.append([a, b, m])
    for a, b, m in seg:
        a0, b0 = max(0.0, a - 0.6), min(gesamt, b + 0.6)
        stueck = musik_stueck(m, b0 - a0)
        i0 = int(a0 * sr)
        musik[:, i0:i0 + stueck.shape[1]] += stueck[:, : n - i0]
    sv = float(regie.get("sfx_lautstaerke", 0.7))
    cache: dict[str, np.ndarray] = {}

    def fx_setzen(art: str, t: float, gain: float, dauer: float | None = None) -> None:
        k = f"{art}:{dauer}"
        if k not in cache:
            cache[k] = klang.effekt(art, dauer)
        _setze_stereo(fx, t, cache[k], gain * sv)

    for i, c in enumerate(clips):
        for art, t, gain, dauer in c[3]["sfx"]:
            fx_setzen(art, starts[i] + t, gain, dauer)
        sz = c[2]
        for e in (sz.get("sfx") or []):
            fx_setzen(e["art"], starts[i] + float(e["bei"]), float(e.get("lautstaerke", 0.8)), e.get("dauer"))
        if i > 0:
            art = sz.get("uebergang_sfx") or s["uebergang_sfx"].get(tnames[i - 1])
            if art and art != "keiner":
                mitte = starts[i] + tds[i - 1] / 2
                lang = {"whoosh": 0.7, "rumble": 2.4, "sparkle": 1.8, "pop": 0.14}.get(art, 1.0)
                fx_setzen(art, max(0.0, mitte - (lang * 0.5 if art == "whoosh" else 0.5)), 0.65)
        if c[3]["kapitel"]:
            fx_setzen("sparkle", starts[i] + (tds[i - 1] if i > 0 else 0) + 0.5, 0.3)

    mp, fp = P.arbeit / "musik.wav", P.arbeit / "effekte.wav"
    klang.schreibe_wav(mp, musik[:, : int(gesamt * sr)])
    klang.schreibe_wav(fp, fx[:, : int(gesamt * sr)])

    # ---- Originalton überblenden
    orig = P.arbeit / "ton_original.wav"
    if len(clips) == 1:
        gA = "[0:a]anull[ac]"
    else:
        teile, cur = [], "0:a"
        for i in range(1, len(clips)):
            out = f"ac{i}"
            teile.append(f"[{cur}][{i}:a]acrossfade=d={tds[i - 1]:.3f}:c1=tri:c2=tri[{out}]")
            cur = out
        teile.append(f"[{cur}]anull[ac]")
        gA = ";".join(teile)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for c in clips:
        cmd += ["-i", c[0]]
    run(cmd + ["-filter_complex", gA, "-map", "[ac]", "-t", sek(gesamt), "-c:a", "pcm_s16le", orig], "Originalton")

    # ---- Mischen: Musik duckt unter Sprache, Effekte bleiben frei
    mv = float(regie.get("musik_lautstaerke", 0.55))
    mix = P.arbeit / "ton_mix.wav"
    gM = (f"[0:a]aresample=48000,asplit=2[o1][o2];"
          f"[1:a]aresample=48000,volume={mv}[m];"
          f"[2:a]aresample=48000[x];"
          f"[m][o1]sidechaincompress=threshold=0.035:ratio=9:attack=20:release=450[md];"
          f"[o2][md][x]amix=inputs=3:duration=first:normalize=0[mx]")
    run(["ffmpeg", "-y", "-v", "error", "-i", orig, "-i", mp, "-i", fp, "-filter_complex", gM,
         "-map", "[mx]", "-t", sek(gesamt), "-c:a", "pcm_s16le", mix], "Tonmischung")

    # ---- Lautheit auf Kino-Streaming-Niveau (zweistufig, sauber)
    ziel_lufs = "-16"
    r = run(["ffmpeg", "-v", "info", "-nostats", "-i", mix, "-af",
             f"loudnorm=I={ziel_lufs}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], "Lautheit messen")
    js = json.loads(r.stderr[r.stderr.rfind("{"): r.stderr.rfind("}") + 1])
    master = P.arbeit / "ton_master.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", mix, "-af",
         f"loudnorm=I={ziel_lufs}:TP=-1.5:LRA=11:measured_I={js['input_i']}:measured_TP={js['input_tp']}:"
         f"measured_LRA={js['input_lra']}:measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true,"
         f"aresample=48000,alimiter=limit=0.89", "-c:a", "pcm_s16le", master], "Lautheit anwenden")

    # ---- Bild: Übergänge, Kapiteltitel, Kino-Format
    gV, cur = [], "0:v"
    for i in range(1, len(clips)):
        out = f"vx{i}"
        gV.append(f"[{cur}][{i}:v]xfade=transition={tnames[i - 1]}:duration={tds[i - 1]:.3f}:offset={starts[i]:.3f}[{out}]")
        cur = out
    gr = Graph(cur)
    bar = 0
    if regie.get("format", "kino") == "kino":
        hoehe = int(round(W / s["kino_format"] / 2) * 2)
        bar = (H - hoehe) // 2
    ti = s["titel"]
    for i, c in enumerate(clips):
        kap = c[3]["kapitel"]
        if not kap:
            continue
        a = starts[i] + (tds[i - 1] if i > 0 else 0) + 0.5
        b = min(a + 3.4, starts[i] + c[1] - (tds[i] if i < len(tds) else 0) - 0.2)
        if b - a < 1.2:
            continue
        kf = P.arbeit / f"kapitel_{i:02d}.txt"
        kf.write_text(kap, encoding="utf-8")
        al = f"if(lt(t,{a + 0.4:.2f}),(t-{a:.2f})/0.4,if(gt(t,{b - 0.4:.2f}),({b:.2f}-t)/0.4,1))"
        ty = H - bar - H * 0.13
        gr.lin(f"drawbox=x={W * 0.07:.0f}:y={ty - H * 0.012:.0f}:w={W * 0.07:.0f}:h=5:color={ti['farbe']}@0.95:t=fill:enable='between(t,{a:.2f},{b:.2f})'")
        gr.lin(f"drawtext={font_opt()}textfile='{ff_text(kf)}':fontsize={H * 0.05:.0f}:fontcolor=white:borderw=2:"
               f"bordercolor=black@0.6:shadowx=2:shadowy=3:x={W * 0.07:.0f}:y={ty:.0f}:enable='between(t,{a:.2f},{b:.2f})':alpha='{al}'")
    if bar:
        gr.lin(f"crop={W}:{H - 2 * bar}:0:{bar},pad={W}:{H}:0:{bar}:black")
    gr.lin("format=yuv420p")
    gV.append(gr.text())

    titel = re.sub(r"[^a-z0-9]+", "-", str(regie.get("titel", "film")).lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("-") or "film"
    nr = 1
    while (P.ausgabe / f"{titel}_v{nr:03d}_{q['name']}.mp4").exists():
        nr += 1
    ziel = P.ausgabe / f"{titel}_v{nr:03d}_{q['name']}.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for c in clips:
        cmd += ["-i", c[0]]
    cmd += ["-i", master, "-filter_complex", ";".join(gV), "-map", f"[{gr.cur}]", "-map", f"{len(clips)}:a",
            "-t", sek(gesamt), "-c:v", "libx264", "-crf", q["crf"], "-preset", q["preset"], "-pix_fmt", "yuv420p",
            "-r", fps, "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", ziel]
    print("Setze alles zusammen ...", flush=True)
    run(cmd, "Endschnitt")

    liste = schnittliste(ziel, regie, clips, starts, tds, tnames, gesamt, js)
    print(f"\nFERTIG: {ziel}\nSchnittliste: {liste}")
    return ziel


def _setze_stereo(buf: np.ndarray, t: float, sig: np.ndarray, gain: float) -> None:
    i = int(round(t * klang.SR))
    if i < 0 or i >= buf.shape[1]:
        return
    k = min(sig.shape[1], buf.shape[1] - i)
    buf[:, i:i + k] += sig[:, :k] * gain


def schnittliste(ziel: Path, regie: dict, clips, starts, tds, tnames, gesamt, js) -> Path:
    z = [f"# Schnittliste – {str(regie.get('titel', 'Film')).replace(chr(10), ' ')}",
         f"_Erstellt {dt.datetime.now():%d.%m.%Y %H:%M}. Länge {gesamt:.1f} s. Lautheit vorher {js['input_i']} LUFS, danach -16 LUFS._", "",
         "| # | Start | Szene | Stimmung | Kapitel | Übergang davor |", "|---|---|---|---|---|---|"]
    for i, c in enumerate(clips):
        sz = c[2]
        name = sz.get("datei") or ("Titelkarte" if i == 0 else "Abspann")
        ue = f"{tnames[i - 1]} ({tds[i - 1]:.1f}s)" if i > 0 else "–"
        z.append(f"| {i + 1} | {starts[i]:.1f}s | {name} | {c[3]['stimmung']} | {c[3]['kapitel']} | {ue} |")
    pfad = ziel.with_name(ziel.stem + "_schnittliste.md")
    pfad.write_text("\n".join(z) + "\n", encoding="utf-8")
    return pfad


# ---------------------------------------------------------------- Befehle
def status(_a=None) -> None:
    ok = lambda b: "ok" if b else "FEHLT"
    print("ffmpeg :", ok(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0))
    fs = szenen_dateien()
    print(f"Szenen : {len(fs)} in {P.szenen}")
    for f in fs:
        print("  -", f.name)
    print("Regie  :", "regie.json" if P.regie.exists() else ("nur Entwurf" if P.entwurf.exists() else "noch keine (analyse)"))
    print("Schrift:", schrift() or "Standard (lege eine Wunschschrift in film/assets/fonts/)")
    eig = [f.name for f in P.musik.glob("*") if f.suffix.lower() in (".wav", ".mp3", ".m4a", ".flac")] if P.musik.exists() else []
    print("Eigene Musik:", ", ".join(eig) or "keine (es wird original komponiert)")
    aus = sorted(P.ausgabe.glob("*.mp4")) if P.ausgabe.exists() else []
    print(f"Ausgabe: {len(aus)} Film(e)")


def auto(args) -> None:
    if not P.regie.exists():
        analyse()
    bauen(args)


def klang_demo(args) -> None:
    klang.demo(Path(args.ordner))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Kino-Pipeline")
    ap.add_argument("--szenen")
    ap.add_argument("--arbeit")
    ap.add_argument("--ausgabe")
    ap.add_argument("--regie")
    ap.add_argument("--musik")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("analyse")
    for n in ("bauen", "auto"):
        sp = sub.add_parser(n)
        sp.add_argument("--vorschau", action="store_true", help="720p, schnell")
        sp.add_argument("--nur", help="nur diese Szenen, z.B. 2,3 (ohne Titelkarte)")
    kd = sub.add_parser("klang")
    kd.add_argument("ordner", nargs="?", default="klang_demo")
    a = ap.parse_args(argv)
    if a.szenen:
        P.szenen = Path(a.szenen)
    if a.arbeit:
        P.arbeit = Path(a.arbeit)
    if a.ausgabe:
        P.ausgabe = Path(a.ausgabe)
    if a.musik:
        P.musik = Path(a.musik)
    if a.regie:
        P.regie = Path(a.regie)
        P.entwurf = Path(a.regie).with_name(Path(a.regie).stem + "_entwurf.json")
    {"status": status, "analyse": analyse, "bauen": bauen, "auto": auto, "klang": klang_demo}[a.cmd](a)


if __name__ == "__main__":
    main()
