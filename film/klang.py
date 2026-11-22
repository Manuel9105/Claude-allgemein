#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Klang: Filmmusik und Soundeffekte, komplett selbst erzeugt.

Alles ist original komponiert und synthetisiert (numpy). Keine Samples,
keine fremden Aufnahmen, keine Rechte-Probleme.
Eigene Musik hat immer Vorrang: Datei in film/musik/<stimmung>.mp3 legen.

Stimmungen: intro, abenteuer, action, spannung, ruhig, sieg, abspann
Effekte:    whoosh, whoosh_lang, boom, stinger, riser, sparkle, zauber,
            rumble, pop, fanfare, herzschlag
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
SKALEN = {"dur": [0, 2, 4, 5, 7, 9, 11], "moll": [0, 2, 3, 5, 7, 8, 10]}

# Vier-Takte-Thema (Skalenstufen, Start in Schlägen, Länge in Schlägen) je Takt.
# Steigt auf, bleibt heldenhaft offen. Wird im ganzen Film wiederkehrend genutzt.
THEMA = [
    [(4, 0.0, 1.5), (5, 1.5, 0.5), (7, 2.0, 2.0)],
    [(5, 0.0, 1.5), (4, 1.5, 0.5), (2, 2.0, 2.0)],
    [(3, 0.0, 1.5), (4, 1.5, 0.5), (5, 2.0, 1.0), (7, 3.0, 1.0)],
    [(6, 0.0, 1.0), (4, 1.0, 1.0), (1, 2.0, 1.0), (4, 3.0, 1.0)],
]

STIMMUNGEN = {
    "intro": dict(bpm=80, mode="dur", root=50, prog=[0, 5, 3, 4], crescendo=True,
                  pad=0.0, bass="lang", bass_ab=0.15, drums="heart", drums_ab=0.0,
                  melodie="blech", melodie_ab=0.55, arp="langsam", arp_ab=0.3, crash=True),
    "abenteuer": dict(bpm=112, mode="dur", root=50, prog=[0, 5, 3, 4],
                      pad=0.0, bass="puls", drums="driving", melodie="blech",
                      arp="schnell", crash=True),
    "action": dict(bpm=138, mode="moll", root=50, prog=[0, 5, 3, 4],
                   pad=0.0, bass="puls", drums="epic", melodie="blech",
                   arp="schnell", crash=True),
    "spannung": dict(bpm=68, mode="moll", root=47, prog=[0, 5, 0, 6],
                     pad=0.0, tief=True, bass="lang", drums="heart",
                     arp="selten", melodie=None),
    "ruhig": dict(bpm=88, mode="dur", root=50, prog=[0, 3, 5, 4],
                  pad=0.0, bass="lang", drums=None, arp="langsam",
                  melodie="glocke", melodie_ab=0.2),
    "sieg": dict(bpm=120, mode="dur", root=50, prog=[0, 3, 4, 0],
                 pad=0.0, bass="puls", drums="epic", melodie="blech",
                 arp="schnell", crash=True),
    "abspann": dict(bpm=100, mode="dur", root=50, prog=[0, 5, 3, 4],
                    pad=0.0, bass="lang", drums="driving_leicht", melodie="glocke",
                    arp="langsam", crash=False),
}


# ---------------------------------------------------------------- Grundbausteine
def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def _n(sek: float) -> int:
    return int(round(sek * SR))


def _t(n: int) -> np.ndarray:
    return np.arange(n) / SR


def rauschen(n: int, rng) -> np.ndarray:
    return rng.standard_normal(n).astype(np.float64)


def band(x: np.ndarray, lo: float | None = None, hi: float | None = None) -> np.ndarray:
    """Weiches Band per FFT. lo = Hochpass, hi = Tiefpass."""
    spek = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    m = np.ones_like(f)
    if lo:
        m *= 1 / (1 + (lo / np.maximum(f, 1.0)) ** 4)
    if hi:
        m *= 1 / (1 + (f / hi) ** 4)
    return np.fft.irfft(spek * m, len(x))


def setze(buf: np.ndarray, start: float, sig: np.ndarray, gain: float = 1.0, pan: float = 0.0) -> None:
    i = _n(start)
    if i >= buf.shape[1] or i < 0:
        return
    n = min(len(sig), buf.shape[1] - i)
    if n <= 0:
        return
    w = (pan + 1) * np.pi / 4
    buf[0, i:i + n] += sig[:n] * gain * np.cos(w)
    buf[1, i:i + n] += sig[:n] * gain * np.sin(w)


def _huellkurve(n: int, attack: float, release: float) -> np.ndarray:
    e = np.ones(n)
    a, r = min(_n(attack), n), min(_n(release), n)
    if a:
        e[:a] = np.linspace(0, 1, a) ** 1.5
    if r:
        e[-r:] *= np.linspace(1, 0, r) ** 1.5
    return e


# ---------------------------------------------------------------- Instrumente
def kick() -> np.ndarray:
    t = _t(_n(0.45))
    f = 45 + 90 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def taiko(freq: float = 62, dauer: float = 1.0, rng=None) -> np.ndarray:
    rng = rng or np.random.default_rng(1)
    t = _t(_n(dauer))
    f = freq * (1 + 1.1 * np.exp(-t * 22))
    koerper = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.2)
    fell = band(rauschen(len(t), rng) * np.exp(-t * 55), hi=2800) * 0.35
    return koerper + fell


def snare(rng) -> np.ndarray:
    t = _t(_n(0.3))
    r = band(rauschen(len(t), rng), 1400, 7500) * np.exp(-t * 17) * 0.75
    k = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 28) * 0.45
    return r + k


def hat(rng, offen: bool = False) -> np.ndarray:
    t = _t(_n(0.25 if offen else 0.07))
    return band(rauschen(len(t), rng), 7000) * np.exp(-t * (14 if offen else 70)) * 0.4


def crash(rng, dauer: float = 2.2) -> np.ndarray:
    t = _t(_n(dauer))
    return band(rauschen(len(t), rng), 3500) * np.exp(-t * 2.4) * 0.5


def zupf(freq: float, dauer: float = 0.4) -> np.ndarray:
    t = _t(_n(dauer))
    s = np.sin(2 * np.pi * freq * t) + 0.45 * np.sin(2 * np.pi * 2 * freq * t) + 0.2 * np.sin(2 * np.pi * 3 * freq * t)
    return s * np.exp(-t * 9) * np.minimum(1, t / 0.004)


def glocke(freq: float, dauer: float = 1.4) -> np.ndarray:
    t = _t(_n(dauer))
    s = (np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * 2.76 * freq * t) * np.exp(-t * 3)
         + 0.3 * np.sin(2 * np.pi * 5.4 * freq * t) * np.exp(-t * 6))
    return s * np.exp(-t * 2.8) * np.minimum(1, t / 0.003)


def flaeche(freq: float, dauer: float, verstimmung: float = 7.0) -> np.ndarray:
    """Streicher-Flächenklang: leicht verstimmte Sägezähne, weich eingeblendet."""
    t = _t(_n(dauer))
    s = np.zeros_like(t)
    for cent in (-verstimmung, 0.0, verstimmung):
        f = freq * 2 ** (cent / 1200)
        for h in range(1, 7):
            s += np.sin(2 * np.pi * f * h * t + h) / h
    return s * _huellkurve(len(t), 0.45, 0.6) / 4.0


def blech(freq: float, dauer: float) -> np.ndarray:
    """Heldenhaftes Blech: Obertöne, Vibrato, Einsatz mit kleinem Anblasen."""
    t = _t(_n(dauer))
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.2 * t) * np.minimum(1, t / 0.4)
    ph = 2 * np.pi * np.cumsum(freq * vib) / SR
    s = np.zeros_like(t)
    for h, g in enumerate([1, 0.8, 0.65, 0.5, 0.4, 0.28, 0.2, 0.12], start=1):
        s += g * np.sin(h * ph)
    return s * _huellkurve(len(t), 0.09, min(0.25, dauer * 0.4)) / 4.0


# ---------------------------------------------------------------- Musik
def _hall(x: np.ndarray, nass: float = 0.16) -> np.ndarray:
    """Weicher Raum, blockweise per FFT (spart Speicher bei langen Stücken)."""
    rng = np.random.default_rng(99)
    ir_n = _n(1.9)
    t = _t(ir_n)
    out = x.copy()
    block = 1 << 17
    for k in range(2):
        ir = band(rauschen(ir_n, rng) * np.exp(-t * 3.4), hi=5500)
        ir[: _n(0.012)] = 0
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
        size = 1 << int(np.ceil(np.log2(block + ir_n)))
        fir = np.fft.rfft(ir, size)
        nass_sig = np.zeros(x.shape[1] + ir_n)
        for a in range(0, x.shape[1], block):
            seg = x[k, a:a + block]
            y = np.fft.irfft(np.fft.rfft(seg, size) * fir, size)[: len(seg) + ir_n]
            nass_sig[a:a + len(y)] += y
        out[k] += nass_sig[: x.shape[1]] * nass
    return out


def komponieren(stimmung: str, dauer: float, seed: int = 7) -> np.ndarray:
    """Liefert ein Stereo-Stück (2, N) float32 in genau `dauer` Sekunden."""
    cfg = STIMMUNGEN[stimmung]
    rng = np.random.default_rng(seed)
    n = _n(dauer) + SR * 3
    buf = np.zeros((2, n))
    spb = 60.0 / cfg["bpm"]
    takt = 4 * spb
    skala = SKALEN[cfg["mode"]]
    root = cfg["root"]

    def deg(d: int) -> int:
        return root + skala[d % 7] + 12 * (d // 7)

    cresc = cfg.get("crescendo", False)
    takte = int(np.ceil(dauer / takt)) + 1
    for b in range(takte):
        t0 = b * takt
        frac = (t0 / max(dauer, 1)) if cresc else 1.0
        ch = cfg["prog"][b % len(cfg["prog"])]
        akkord = [deg(ch), deg(ch + 2), deg(ch + 4)]
        gain_c = 0.35 + 0.65 * frac if cresc else 1.0

        # Fläche
        if frac >= cfg.get("pad", 0.0):
            for k, m in enumerate(akkord):
                setze(buf, t0, flaeche(midi(m), takt * 1.2), 0.16 * gain_c, pan=(-0.45, 0.0, 0.45)[k])
            setze(buf, t0, flaeche(midi(akkord[0] - 12), takt * 1.2), 0.2 * gain_c, 0.0)
            if cfg.get("tief"):
                setze(buf, t0, flaeche(midi(akkord[0] - 24), takt * 1.25, 3), 0.28, 0.0)

        # Bass
        if cfg.get("bass") and frac >= cfg.get("bass_ab", 0.0):
            wurzel = midi(akkord[0] - 24)
            if cfg["bass"] == "lang":
                t = _t(_n(takt * 1.05))
                s = (np.sin(2 * np.pi * wurzel * t) + 0.3 * np.sin(4 * np.pi * wurzel * t)) * _huellkurve(len(t), 0.05, 0.4)
                setze(buf, t0, s, 0.32)
            else:
                for st in range(8):
                    t = _t(_n(spb * 0.48))
                    s = (np.sin(2 * np.pi * wurzel * t) + 0.35 * np.sin(4 * np.pi * wurzel * t)) * np.exp(-t * 6)
                    setze(buf, t0 + st * spb / 2, s, 0.3 if st % 2 == 0 else 0.2)

        # Schlagwerk
        stil = cfg.get("drums")
        if stil and frac >= cfg.get("drums_ab", 0.0):
            letzter = (b % 4 == 3)
            for s in range(16):
                ts = t0 + s * spb / 4
                if stil == "heart":
                    if s == 0:
                        setze(buf, ts, taiko(55, 1.0, rng), 0.55 * gain_c)
                    if s == 6:
                        setze(buf, ts, taiko(55, 0.8, rng), 0.35 * gain_c)
                elif stil in ("driving", "driving_leicht"):
                    leicht = 0.6 if stil == "driving_leicht" else 1.0
                    if s in (0, 8, 10):
                        setze(buf, ts, kick(), 0.65 * leicht)
                    if s in (4, 12):
                        setze(buf, ts, snare(rng), 0.5 * leicht)
                    if s % 2 == 0:
                        setze(buf, ts, hat(rng, offen=(s == 14)), 0.32 * leicht, pan=0.3)
                    if s == 0 and stil == "driving":
                        setze(buf, ts, taiko(62, 0.9, rng), 0.35)
                elif stil == "epic":
                    if s in (0, 4, 8, 12):
                        setze(buf, ts, kick(), 0.7)
                    if s in (0, 6, 8, 14):
                        setze(buf, ts, taiko(58 if s in (0, 8) else 66, 0.9, rng), 0.55)
                    if s in (4, 12):
                        setze(buf, ts, snare(rng), 0.6)
                    setze(buf, ts, hat(rng), 0.18, pan=0.3)
                    if letzter and s >= 8:
                        setze(buf, ts, taiko(80 + (s - 8) * 9, 0.4, rng), 0.5, pan=(-0.4 + (s - 8) * 0.12))
            if cfg.get("crash") and b % 4 == 0 and b > 0:
                setze(buf, t0, crash(rng), 0.3)

        # Arpeggio
        art = cfg.get("arp")
        if art and frac >= cfg.get("arp_ab", 0.0):
            hoch = [akkord[0] + 12, akkord[1] + 12, akkord[2] + 12, akkord[1] + 24]
            if art == "schnell":
                muster = [0, 1, 2, 3, 2, 1, 2, 3, 0, 1, 2, 3, 2, 1, 3, 2]
                for s in range(16):
                    setze(buf, t0 + s * spb / 4, zupf(midi(hoch[muster[s]]), 0.25), 0.11, pan=0.35 if s % 2 else -0.35)
            elif art == "langsam":
                for s in range(8):
                    setze(buf, t0 + s * spb / 2, zupf(midi(hoch[[0, 1, 2, 3, 2, 1, 2, 1][s]]), 0.5), 0.11, pan=0.3 if s % 2 else -0.3)
            elif art == "selten":
                for s in (3, 11):
                    setze(buf, t0 + s * spb / 2, glocke(midi(hoch[3] + 12), 1.6), 0.07, pan=rng.uniform(-0.6, 0.6))

        # Thema
        mel = cfg.get("melodie")
        if mel and frac >= cfg.get("melodie_ab", 0.0):
            for (d, start, laenge) in THEMA[b % 4]:
                ton = deg(d + 7)
                ts = t0 + start * spb
                if mel == "blech":
                    setze(buf, ts, blech(midi(ton), laenge * spb * 0.95), 0.42 * gain_c)
                else:
                    setze(buf, ts, glocke(midi(ton + 12), 1.6), 0.2)

    buf = _hall(buf, 0.17)[:, : _n(dauer)]
    buf = np.tanh(buf * 0.9)
    buf *= 0.85 / (np.max(np.abs(buf)) + 1e-9)
    buf *= np.minimum(1, np.arange(buf.shape[1]) / (0.25 * SR))
    ende = min(buf.shape[1], _n(2.2))
    buf[:, -ende:] *= np.linspace(1, 0, ende) ** 1.6
    return buf.astype(np.float32)


# ---------------------------------------------------------------- Effekte
def _stereo(mono_l: np.ndarray, mono_r: np.ndarray | None = None) -> np.ndarray:
    r = mono_l if mono_r is None else mono_r
    out = np.stack([mono_l, r])
    return (out * 0.9 / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)


def effekt(art: str, dauer: float | None = None, seed: int = 5) -> np.ndarray:
    """Liefert einen Effekt als Stereo-Array (2, N) float32, Spitze 0.9."""
    rng = np.random.default_rng(seed)

    if art in ("whoosh", "whoosh_lang"):
        d = dauer or (0.7 if art == "whoosh" else 1.6)
        t = _t(_n(d))
        x = t / d
        tief = (x ** 1.2) * (1 - x) ** 1.6
        hoch = (x ** 2.4) * (1 - x) ** 0.9
        kanaele = []
        for _ in range(2):
            r = rauschen(len(t), rng)
            s = band(r, 300, 1800) * tief / (tief.max() + 1e-9) + 0.8 * band(r, 2200, 9000) * hoch / (hoch.max() + 1e-9)
            kanaele.append(s)
        return _stereo(*kanaele)

    if art == "boom":
        d = dauer or 2.8
        t = _t(_n(d))
        f = 36 + 80 * np.exp(-t * 13)
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.9)
        s += band(rauschen(len(t), rng), hi=420) * np.exp(-t * 7) * 0.9
        s += band(rauschen(len(t), rng), hi=180) * np.exp(-t * 1.3) * 0.18
        return _stereo(s)

    if art == "stinger":
        d = dauer or 3.0
        b = effekt("boom", d)[0].astype(np.float64)
        t = _t(len(b))
        crash_s = band(rauschen(len(t), rng), 3000) * np.exp(-t * 2.6) * 0.45
        akk = np.zeros(len(t))
        for m in (50, 57, 62, 66):
            blk = blech(midi(m), 1.1)
            akk[: len(blk)] += blk * 0.5
        return _stereo(b + crash_s + akk)

    if art == "riser":
        d = dauer or 3.0
        t = _t(_n(d))
        x = t / d
        r = band(rauschen(len(t), rng), 500) * x ** 2.2
        f = 180 * (1 + 9 * x ** 1.6)
        ton = np.sin(2 * np.pi * np.cumsum(f) / SR) * x ** 2 * 0.5
        return _stereo(r + ton)

    if art in ("sparkle", "zauber"):
        d = dauer or 1.8
        out = np.zeros((2, _n(d) + SR))
        pent = [0, 2, 4, 7, 9]
        anz = 16 if art == "sparkle" else 22
        for i in range(anz):
            st = (d * 0.85) * (i / anz) ** (1.0 if art == "sparkle" else 0.7) + rng.uniform(0, 0.04)
            ton = 86 + pent[int(rng.integers(0, 5))] + 12 * int(rng.integers(0, 2))
            if art == "zauber":
                ton = 74 + i * 1.3
            n_ = _n(0.45)
            t = _t(n_)
            s = (np.sin(2 * np.pi * midi(ton) * t) + 0.3 * np.sin(4 * np.pi * midi(ton) * t)) * np.exp(-t * 9)
            setze(out, st, s, 0.5, pan=rng.uniform(-0.8, 0.8))
        res = out[:, : _n(d + 0.3)]
        return (res * 0.9 / (np.max(np.abs(res)) + 1e-9)).astype(np.float32)

    if art == "rumble":
        d = dauer or 2.4
        t = _t(_n(d))
        s = band(rauschen(len(t), rng), 25, 110) * np.sin(np.pi * t / d) ** 2
        s += 0.4 * np.sin(2 * np.pi * 41 * t) * np.sin(np.pi * t / d)
        return _stereo(s)

    if art == "pop":
        t = _t(_n(0.14))
        f = 700 * np.exp(-t * 28) + 120
        return _stereo(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 30))

    if art == "fanfare":
        out = np.zeros((2, _n(3.4)))
        akkorde = [(0.0, (62, 66, 69), 0.5), (0.5, (67, 71, 74), 0.5), (1.0, (62, 66, 69, 74), 2.2)]
        for st, noten, lg in akkorde:
            for m in noten:
                setze(out, st, blech(midi(m), lg), 0.5, pan=rng.uniform(-0.3, 0.3))
        setze(out, 1.0, taiko(60, 1.4, rng), 0.7)
        setze(out, 1.0, crash(rng, 2.0), 0.35)
        return (out * 0.9 / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)

    if art == "herzschlag":
        out = np.zeros((2, _n(1.4)))
        setze(out, 0.0, taiko(52, 0.7, rng), 0.9)
        setze(out, 0.27, taiko(52, 0.7, rng), 0.6)
        return (out * 0.9 / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)

    raise KeyError(f"Unbekannter Effekt: {art}")


EFFEKTE = ["whoosh", "whoosh_lang", "boom", "stinger", "riser", "sparkle", "zauber",
           "rumble", "pop", "fanfare", "herzschlag"]


# ---------------------------------------------------------------- Ein/Ausgabe
def schreibe_wav(pfad: Path, arr: np.ndarray) -> None:
    pcm = (np.clip(arr, -1, 1).T * 32767).astype("<i2")
    with wave.open(str(pfad), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def lade_audio(pfad: Path) -> np.ndarray:
    """Beliebige Audiodatei (mp3, wav, m4a ...) als Stereo (2, N) float32 laden."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(pfad), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]
    roh = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(roh, dtype=np.float32).reshape(-1, 2).T.copy()


def auf_laenge(arr: np.ndarray, dauer: float) -> np.ndarray:
    """Eigene Musik auf Länge bringen: schleifen mit Überblendung, dann ausblenden."""
    n = _n(dauer)
    if arr.shape[1] >= n:
        out = arr[:, :n].copy()
    else:
        ueb = min(_n(1.5), arr.shape[1] // 4)
        out = arr.copy()
        while out.shape[1] < n:
            a = out[:, -ueb:] * np.linspace(1, 0, ueb)
            b = arr[:, :ueb] * np.linspace(0, 1, ueb)
            out = np.concatenate([out[:, :-ueb], a + b, arr[:, ueb:]], axis=1)
        out = out[:, :n]
    ende = min(n, _n(2.0))
    out[:, -ende:] *= np.linspace(1, 0, ende)
    out[:, : min(n, _n(0.3))] *= np.linspace(0, 1, min(n, _n(0.3)))
    return out


def demo(ordner: Path) -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    for st in STIMMUNGEN:
        schreibe_wav(ordner / f"musik_{st}.wav", komponieren(st, 24))
        print("Musik", st)
    for e in EFFEKTE:
        schreibe_wav(ordner / f"sfx_{e}.wav", effekt(e))
        print("Effekt", e)


if __name__ == "__main__":
    import sys
    demo(Path(sys.argv[1] if len(sys.argv) > 1 else "demo_klang"))
