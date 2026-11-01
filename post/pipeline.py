#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-Pipeline für Manuel Kappernagel.

Arbeitsteilung:
  Das Skript macht nur sichere, prüfbare Schritte.
  Das Urteil (aufteilen, einordnen, Fristen lesen) macht Claude.
  Claude schreibt sein Urteil in einen Plan (plan.json).
  Das Skript prüft den Plan und führt ihn aus.

Garantien, egal was gescannt wird:
  - Das Original wird zuerst archiviert. Es wird nie verändert oder gelöscht.
  - Es wird nie etwas überschrieben. Gleicher Name bekommt _2, _3 ...
  - Keine Seite geht verloren. Jede Seite ist zugeordnet oder bewusst weggelassen.
  - Ein Scan wird nicht zweimal verarbeitet (Prüfsumme).
  - Protokoll und Fristen werden nur angehängt.
  - Keine IBAN und keine langen Nummern in Namen, Protokoll oder Fristen.
  - Unsicheres landet in 99_Unklar.

Aufruf: uv run --with pypdf python post/pipeline.py <befehl> [optionen]
Befehle: status, bekannt, extract, zeige, validate, apply, fristen, erledigt
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover
    sys.exit("pypdf fehlt. Starte so: uv run --with pypdf python post/pipeline.py ...")

EINGANG = "00 ScanEingang"
ARCHIV = "01_Archiv-Original"
POST = "Post"
SYSTEM = "_System"
UNKLAR = "99_Unklar"

PROTOKOLL_KOPF = ["Zeitpunkt", "Originaldatei", "Seiten", "Neuer Name", "Zielordner", "Frist", "Hinweis"]
FRISTEN_KOPF = ["id", "datum", "art", "betrag", "status", "bereich", "absender", "betreff", "datei", "angelegt"]
ERLEDIGT_KOPF = ["id", "am", "notiz"]

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){3,7}(?:\s?[0-9A-Z]{1,4})?\b")
LANGE_ZAHL_RE = re.compile(r"\d{9,}")
SEITE_VON_RE = re.compile(r"S\s*e\s*i\s*t\s*e\s+(\d{1,3})\s+v\s*o\s*n\s+(\d{1,3})", re.I)
DATUM_RE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b")
BETRAG_RE = re.compile(r"\b(\d{1,3}(?:\.\d{3})*,\d{2})\s?(?:€|EUR)", re.I)
NAME_TEIL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{0,39}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
START_SIGNALE = ("sehr geehrte", "sehr geehrter", "hamburg, den", "lübeck, den", "mahnung",
                 "anhörung im bußgeld", "schlussrechnung", "rechnungsnummer", "bescheid")


# ----------------------------------------------------------------- Helfer

def heute(args) -> dt.date:
    if getattr(args, "heute", None):
        return dt.date.fromisoformat(args.heute)
    return dt.date.today()


def jetzt() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def finde_basis(arg: str | None) -> Path:
    kandidaten: list[Path] = []
    if arg:
        kandidaten.append(Path(arg).expanduser())
    if os.environ.get("POST_BASIS"):
        kandidaten.append(Path(os.environ["POST_BASIS"]).expanduser())
    home = Path.home()
    kandidaten.append(home / "Dropbox")
    cs = home / "Library" / "CloudStorage"
    if cs.is_dir():
        kandidaten += sorted(cs.glob("Dropbox*"))
    for k in kandidaten:
        if (k / EINGANG).is_dir():
            return k
    sys.exit(f"Dropbox-Basis mit Ordner '{EINGANG}' nicht gefunden. Gib --basis PFAD an.")


class Pfade:
    def __init__(self, basis: Path):
        self.basis = basis
        self.eingang = basis / EINGANG
        self.archiv = basis / ARCHIV
        self.post = basis / POST
        self.system = self.post / SYSTEM
        self.arbeit = self.system / "arbeit"
        self.state = self.system / "verarbeitet.json"
        self.protokoll = self.post / "_Protokoll.csv"
        self.fristen_daten = self.post / "_Fristen_Daten.csv"
        self.fristen_erledigt = self.post / "_Fristen_Erledigt.csv"
        self.fristen_ansicht = self.post / "_Fristen_Aktuell.md"


def lade_regeln(pfad: str | None, p: Pfade) -> dict:
    kandidaten = []
    if pfad:
        kandidaten.append(Path(pfad))
    kandidaten += [p.system / "regeln.json", Path(__file__).with_name("regeln.json")]
    for k in kandidaten:
        if k.is_file():
            return json.loads(k.read_text(encoding="utf-8"))
    sys.exit("regeln.json nicht gefunden.")


def sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def lade_state(p: Pfade) -> dict:
    if p.state.is_file():
        return json.loads(p.state.read_text(encoding="utf-8"))
    return {}


def speichere_state(p: Pfade, state: dict) -> None:
    p.system.mkdir(parents=True, exist_ok=True)
    tmp = p.state.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p.state)  # eigene Statusdatei, kein Nutzerdokument


def freier_pfad(pfad: Path) -> Path:
    """Gibt einen Pfad zurück, der nicht existiert. Hängt _2, _3 ... an."""
    if not pfad.exists():
        return pfad
    stamm, endung = pfad.stem, pfad.suffix
    n = 2
    while True:
        neu = pfad.with_name(f"{stamm}_{n}{endung}")
        if not neu.exists():
            return neu
        n += 1


def schreibe_neu(pfad: Path, schreiber) -> Path:
    """Legt eine neue Datei an. Überschreibt nie (Modus 'xb')."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    while True:
        ziel = freier_pfad(pfad)
        try:
            with open(ziel, "xb") as f:
                schreiber(f)
            return ziel
        except FileExistsError:
            continue


def haenge_zeile_an(pfad: Path, kopf: list[str], zeile: list[str]) -> None:
    neu = not pfad.exists()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if neu:
            w.writerow(kopf)
        w.writerow(zeile)


def lies_csv(pfad: Path) -> list[dict]:
    if not pfad.is_file():
        return []
    with open(pfad, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def reinige(teil: str) -> str:
    t = teil.strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = re.sub(r"[\s_]+", "-", t)
    t = re.sub(r"[^A-Za-z0-9\-]", "", t)
    return re.sub(r"-{2,}", "-", t).strip("-")


def sensibel(text: str) -> bool:
    return bool(IBAN_RE.search(text) or LANGE_ZAHL_RE.search(text.replace(" ", "")))


def entspace(text: str) -> str:
    """Macht aus 'M A H N U N G' wieder 'MAHNUNG' (Scanner-OCR mit Leerzeichen)."""
    buchstabe = r"[A-Za-zÄÖÜäöüß]"
    alt = None
    while alt != text:
        alt = text
        text = re.sub(rf"(?<=\b{buchstabe}) (?={buchstabe}\b)", "", text)
    return text


def iso_datum(tag: str, monat: str, jahr: str) -> str | None:
    try:
        return dt.date(int(jahr), int(monat), int(tag)).isoformat()
    except ValueError:
        return None


# ----------------------------------------------------------------- Seiten lesen

def seiten_info(reader: PdfReader, regeln: dict, text_laenge: int) -> list[dict]:
    grenze = regeln.get("leere_seite_unter_zeichen", 15)
    out = []
    for i, seite in enumerate(reader.pages, 1):
        try:
            roh = seite.extract_text() or ""
        except Exception:
            roh = ""
        roh = re.sub(r"[ \t]+", " ", roh)
        norm = entspace(roh)
        zeichen = len(re.sub(r"\W", "", norm))
        m = SEITE_VON_RE.search(norm)
        daten, seen = [], set()
        for d in DATUM_RE.finditer(norm[:1500]):
            iso = iso_datum(*d.groups())
            if iso and iso not in seen:
                seen.add(iso)
                daten.append(iso)
        out.append({
            "seite": i,
            "zeichen": zeichen,
            "leer": zeichen < grenze,
            "wenig_text": grenze <= zeichen < 80,
            "marker": [int(m.group(1)), int(m.group(2))] if m else None,
            "daten": daten[:6],
            "betraege": list(dict.fromkeys(BETRAG_RE.findall(norm)))[:6],
            "anfang": " ".join(norm.split())[:text_laenge],
            "_norm": norm,
        })
    return out


def beginnt_neu(s: dict, vorher: dict) -> bool:
    ms, mv = s["marker"], vorher["marker"]
    if ms and mv:
        return ms[1] != mv[1]
    kopf = s["_norm"][:700].lower()
    return any(sig in kopf for sig in START_SIGNALE)


def ordne(gruppe: list[dict]) -> list[dict]:
    marker = [s["marker"] for s in gruppe]
    if len(gruppe) > 1 and all(marker):
        ks = [m[0] for m in marker]
        if ks == sorted(ks, reverse=True) and len(set(ks)) == len(ks):
            return list(reversed(gruppe))
    return gruppe


def segmentiere(seiten: list[dict]) -> list[list[dict]]:
    inhalt = [s for s in seiten if not s["leer"]]
    gruppen: list[list[dict]] = []
    aktuell: list[dict] = []
    for s in inhalt:
        if aktuell and beginnt_neu(s, aktuell[-1]):
            gruppen.append(aktuell)
            aktuell = []
        aktuell.append(s)
    if aktuell:
        gruppen.append(aktuell)
    return gruppen


def passt(regel: dict, text: str) -> int:
    alle = regel.get("wenn_alle", [])
    eine = regel.get("wenn_eine", [])
    if alle and not all(w in text for w in alle):
        return 0
    treffer = sum(1 for w in eine if w in text)
    if eine and treffer == 0:
        return 0
    return len(alle) + treffer or 0


def klassifiziere(text: str, regeln: dict) -> tuple[str, str, float]:
    text = text.lower()
    beste = None
    for r in regeln["zuordnung"]:
        n = passt(r, text)
        if n:
            schluessel = (r.get("prioritaet", 0), n)
            if beste is None or schluessel > beste[0]:
                beste = (schluessel, r)
    if not beste:
        return UNKLAR, "keine Regel", 0.3
    sicher = min(0.55 + 0.05 * beste[0][1] + beste[0][0] / 400, 0.9)
    return beste[1]["ziel"], beste[1]["name"], round(sicher, 2)


def kurz(text: str, liste: list[dict], standard: str) -> str:
    t = text.lower()
    for e in liste:
        if e["muster"] in t:
            return e["kurz"]
    return standard


def vorschlag(seiten: list[dict], regeln: dict) -> dict:
    docs = []
    for g in segmentiere(seiten):
        g = ordne(g)
        text = " ".join(s["_norm"] for s in g)
        ziel, regel, sicher = klassifiziere(text, regeln)
        datum = next((d for s in g for d in s["daten"]), None)
        docs.append({
            "seiten": [s["seite"] for s in g],
            "regel": regel,
            "ziel": ziel,
            "sicherheit": sicher,
            "datum": datum,
            "absender": kurz(text[:2500], regeln["absender"], "Absender"),
            "betreff": kurz(text[:2500], regeln["betreff"], "Schreiben"),
            "betraege": list(dict.fromkeys(b for s in g for b in s["betraege"]))[:6],
        })
    leer = [s["seite"] for s in seiten if s["leer"]]
    return {"dokumente": docs, "leer": leer}


# ----------------------------------------------------------------- Befehle

def scans_im_eingang(p: Pfade) -> list[Path]:
    return sorted(x for x in p.eingang.iterdir() if x.is_file() and x.suffix.lower() == ".pdf")


def cmd_status(a, p: Pfade, regeln: dict) -> int:
    state = lade_state(p)
    scans = scans_im_eingang(p)
    neu = 0
    for s in scans:
        h = sha256(s)
        ok = h in state
        neu += 0 if ok else 1
        print(f"{'erledigt' if ok else 'NEU     '}  {s.name}")
    print(f"\n{neu} neue Scans von {len(scans)} im Eingang ({p.eingang})")
    return 0


def baue_entwurf(ergebnis: dict, regeln: dict) -> dict:
    """Vollständiger Plan, der immer gültig ist. Rückfall, wenn niemand sonst urteilt.
    Alles Unsichere und alles ohne Text geht ungeteilt nach 99_Unklar."""
    scans = []
    for s in ergebnis["scans"]:
        if s.get("fehler"):
            continue
        v = s["vorschlag"]
        docs = []
        if s["ocr_noetig"] or not v["dokumente"]:
            docs.append({"seiten": list(range(1, s["seiten_anzahl"] + 1)), "ziel": UNKLAR, "sicherheit": 0.0,
                         "datum": None, "absender": "Unbekannt", "betreff": "Scan-ohne-Text-ungeteilt", "fristen": []})
            weg = []
        else:
            for d in v["dokumente"]:
                docs.append({"seiten": d["seiten"], "ziel": d["ziel"], "sicherheit": d["sicherheit"], "datum": d["datum"],
                             "absender": d["absender"], "betreff": d["betreff"], "fristen": []})
            weg = [{"seite": n, "grund": "leer"} for n in v["leer"]]
        scans.append({"datei": s["datei"], "sha256": s["sha256"], "dokumente": docs, "weggelassen": weg})
    return {"_hinweis": "Entwurf. Fristen sind leer. Claude ergänzt Urteil und Fristen.", "scans": scans}


def cmd_extract(a, p: Pfade, regeln: dict) -> int:
    state = lade_state(p)
    ergebnis = {"erstellt": jetzt(), "scans": []}
    for pdf in scans_im_eingang(p):
        h = sha256(pdf)
        if h in state and not a.alle:
            continue
        try:
            reader = PdfReader(str(pdf))
        except Exception as e:
            ergebnis["scans"].append({"datei": pdf.name, "sha256": h, "fehler": f"nicht lesbar: {e}"})
            continue
        seiten = seiten_info(reader, regeln, a.zeichen)
        ocr = all(s["leer"] for s in seiten)
        scan = {
            "datei": pdf.name, "sha256": h, "seiten_anzahl": len(seiten),
            "ocr_noetig": ocr,
            "seiten": [{k: v for k, v in s.items() if k != "_norm"} for s in seiten],
            "vorschlag": vorschlag(seiten, regeln),
        }
        ergebnis["scans"].append(scan)
    p.arbeit.mkdir(parents=True, exist_ok=True)
    ziel = p.arbeit / "extract.json"
    ziel.write_text(json.dumps(ergebnis, ensure_ascii=False, indent=2), encoding="utf-8")
    entwurf = p.arbeit / "plan_entwurf.json"
    entwurf.write_text(json.dumps(baue_entwurf(ergebnis, regeln), ensure_ascii=False, indent=2), encoding="utf-8")
    if not ergebnis["scans"]:
        print("Keine neuen Scans.")
        return 0
    for s in ergebnis["scans"]:
        print(f"\n=== {s['datei']}  ({s.get('seiten_anzahl', '?')} Seiten)")
        if s.get("fehler"):
            print("   FEHLER:", s["fehler"])
            continue
        if s["ocr_noetig"]:
            print("   ACHTUNG: kein Text erkannt. OCR nötig (ocrmypdf). Bis dahin ungeteilt nach 99_Unklar.")
        for pg in s["seiten"]:
            mark = f"S.{pg['marker'][0]}/{pg['marker'][1]}" if pg["marker"] else "      "
            flag = "LEER " if pg["leer"] else ("WENIG" if pg.get("wenig_text") else "     ")
            print(f"   {pg['seite']:>3} {mark:>8} {flag}{pg['anfang'][:90]}")
        v = s["vorschlag"]
        print("   -- Vorschlag (nur Entwurf) --")
        for d in v["dokumente"]:
            print(f"   Seiten {d['seiten']} -> {d['ziel']} ({d['regel']}, {int(d['sicherheit']*100)}%)")
        if v["leer"]:
            print(f"   leere Seiten: {v['leer']}")
    print(f"\nGeschrieben: {ziel}")
    return 0


def cmd_zeige(a, p: Pfade, regeln: dict) -> int:
    pdf = p.eingang / a.datei
    if not pdf.is_file():
        pdf = Path(a.datei)
    reader = PdfReader(str(pdf))
    nummern = a.seiten or list(range(1, len(reader.pages) + 1))
    for n in nummern:
        if not 1 <= n <= len(reader.pages):
            print(f"Seite {n}: gibt es nicht.")
            continue
        print(f"----- Seite {n} -----")
        print(entspace(reader.pages[n - 1].extract_text() or "(kein Text)"))
    return 0


def baue_name(d: dict, scan_datum: str) -> tuple[str, list[str]]:
    hinweise = []
    datum = d.get("datum")
    if not datum or not ISO_RE.match(datum):
        datum = scan_datum
        hinweise.append("Datum geschätzt (Scandatum)")
    elif d.get("datum_geschaetzt"):
        hinweise.append("Datum geschätzt")
    return f"{datum}_{reinige(d['absender'])}_{reinige(d['betreff'])}.pdf", hinweise


def pruefe_plan(a, p: Pfade, regeln: dict, plan: dict) -> tuple[list[dict], list[str], list[str]]:
    fehler: list[str] = []
    warnungen: list[str] = []
    zeilen: list[dict] = []
    erlaubt = set(regeln["ziele"])
    scan_datum = dt.date.today().isoformat()
    for sc in plan.get("scans", []):
        pdf = p.eingang / sc["datei"]
        if not pdf.is_file():
            fehler.append(f"{sc['datei']}: Datei nicht im Eingang.")
            continue
        if sha256(pdf) != sc.get("sha256"):
            fehler.append(f"{sc['datei']}: Prüfsumme passt nicht. Plan ist veraltet, bitte extract neu.")
            continue
        n = len(PdfReader(str(pdf)).pages)
        belegt: dict[int, str] = {}
        eintraege = [(f"Dokument {i+1}", d["seiten"], d) for i, d in enumerate(sc.get("dokumente", []))]
        for w in sc.get("weggelassen", []):
            eintraege.append((f"weggelassen S.{w.get('seite')}", [w.get("seite")], None))
        for bez, seiten, _ in eintraege:
            for s in seiten:
                if not isinstance(s, int) or not 1 <= s <= n:
                    fehler.append(f"{sc['datei']} {bez}: Seite {s} gibt es nicht (1..{n}).")
                elif s in belegt:
                    fehler.append(f"{sc['datei']}: Seite {s} doppelt ({belegt[s]} und {bez}).")
                else:
                    belegt[s] = bez
        reader_pruef = PdfReader(str(pdf))
        for w in sc.get("weggelassen", []):
            sn = w.get("seite")
            if w.get("grund") == "leer" and isinstance(sn, int) and 1 <= sn <= n:
                try:
                    txt = reader_pruef.pages[sn - 1].extract_text() or ""
                except Exception:
                    txt = ""
                if len(re.sub(r"\W", "", txt)) >= regeln.get("leere_seite_unter_zeichen", 15):
                    fehler.append(f"{sc['datei']}: Seite {sn} hat Text und darf nicht als leer weggelassen werden.")
        fehlt = [s for s in range(1, n + 1) if s not in belegt]
        if fehlt:
            fehler.append(f"{sc['datei']}: Seiten nicht zugeordnet: {fehlt}. Es darf keine Seite fehlen.")
        for i, d in enumerate(sc.get("dokumente", []), 1):
            hinweise: list[str] = []
            kaputt = False
            for feld in ("absender", "betreff"):
                if not d.get(feld) or not NAME_TEIL_RE.match(reinige(d[feld])):
                    fehler.append(f"{sc['datei']} Dok {i}: '{feld}' fehlt oder ist unbrauchbar.")
                    kaputt = True
            if kaputt:
                continue
            name, h = baue_name(d, scan_datum)
            hinweise += h
            ziel = d.get("ziel", "")
            if ".." in ziel or ziel.startswith("/") or ziel not in erlaubt:
                fehler.append(f"{sc['datei']} Dok {i}: Ziel '{ziel}' nicht erlaubt. In regeln.json ergänzen.")
                continue
            sicher = float(d.get("sicherheit", 0))
            if sicher < regeln["schwelle"] and not d.get("bestaetigt") and ziel != UNKLAR:
                hinweise.append(f"unsicher ({int(sicher*100)}%), geht nach {UNKLAR}")
                ziel = UNKLAR
            for text in (name, d.get("absender", ""), d.get("betreff", ""), json.dumps(d.get("fristen", []), ensure_ascii=False)):
                if sensibel(text):
                    fehler.append(f"{sc['datei']} Dok {i}: enthält IBAN oder lange Nummer. Bitte entfernen.")
                    break
            for f in d.get("fristen", []):
                if f.get("datum") and not ISO_RE.match(f["datum"]):
                    fehler.append(f"{sc['datei']} Dok {i}: Fristdatum '{f['datum']}' ist nicht JJJJ-MM-TT.")
                if f.get("art") and f["art"] not in regeln["fristarten"]:
                    warnungen.append(f"{sc['datei']} Dok {i}: Fristart '{f['art']}' unbekannt, wird 'Sonstiges'.")
            zeilen.append({"scan": sc["datei"], "sha": sc["sha256"], "nr": i, "seiten": d["seiten"], "name": name,
                           "ziel": ziel, "fristen": d.get("fristen", []), "sicher": sicher,
                           "hinweis": "; ".join(hinweise), "absender": d["absender"], "betreff": d["betreff"]})
        for w in sc.get("weggelassen", []):
            if w.get("grund") not in ("leer", "doppelt"):
                warnungen.append(f"{sc['datei']} S.{w.get('seite')}: Weglass-Grund '{w.get('grund')}' ist ungewöhnlich.")
    return zeilen, fehler, warnungen


def lade_plan(a, p: Pfade) -> dict:
    pfad = Path(a.plan) if a.plan else p.arbeit / "plan.json"
    if not pfad.is_file():
        sys.exit(f"Plan nicht gefunden: {pfad}")
    return json.loads(pfad.read_text(encoding="utf-8"))


def cmd_validate(a, p: Pfade, regeln: dict) -> int:
    plan = lade_plan(a, p)
    zeilen, fehler, warnungen = pruefe_plan(a, p, regeln, plan)
    print("| Scan | Seiten | Neuer Dateiname | Zielordner | Frist | Sicherheit | Hinweis |")
    print("|---|---|---|---|---|---|---|")
    for z in zeilen:
        fr = ", ".join(f"{f.get('datum') or 'ohne Datum'} {f.get('art','')}".strip() for f in z["fristen"]) or "-"
        print(f"| {z['scan']} | {z['seiten']} | {z['name']} | {z['ziel']} | {fr} | {int(z['sicher']*100)}% | {z['hinweis'] or '-'} |")
    for w in warnungen:
        print("WARNUNG:", w)
    for f in fehler:
        print("FEHLER:", f)
    if fehler:
        print(f"\nPlan ist NICHT ausführbar ({len(fehler)} Fehler).")
        return 1
    print(f"\nPlan ist in Ordnung: {len(zeilen)} Dokumente. Nichts wurde verändert.")
    return 0


def fristen_neu_anlegen(p: Pfade, z: dict, regeln: dict, datei_rel: str) -> int:
    n = 0
    vorhanden = {r["id"] for r in lies_csv(p.fristen_daten)}
    bereich = z["ziel"].split("/")[0]
    for f in z["fristen"]:
        art = f.get("art") if f.get("art") in regeln["fristarten"] else "Sonstiges"
        basis = f"{datei_rel}|{f.get('datum')}|{art}|{f.get('betrag')}"
        fid = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:8]
        if fid in vorhanden:
            continue
        haenge_zeile_an(p.fristen_daten, FRISTEN_KOPF, [
            fid, f.get("datum") or "", art, f.get("betrag") or "", f.get("status") or "genannt",
            bereich, z["absender"], z["betreff"], datei_rel, jetzt()])
        n += 1
    return n


def cmd_apply(a, p: Pfade, regeln: dict) -> int:
    plan = lade_plan(a, p)
    zeilen, fehler, warnungen = pruefe_plan(a, p, regeln, plan)
    if fehler:
        for f in fehler:
            print("FEHLER:", f)
        print("Abbruch. Es wurde nichts verändert.")
        return 1
    state = lade_state(p)
    trocken = not a.ja
    print("TROCKENLAUF (nichts wird geschrieben). Mit --ja ausführen.\n" if trocken else "AUSFÜHREN\n")
    scans: dict[str, list[dict]] = {}
    for z in zeilen:
        scans.setdefault(z["scan"], []).append(z)
    for datei, docs in scans.items():
        pdf = p.eingang / datei
        h = docs[0]["sha"]
        if h in state and not a.nochmal:
            print(f"{datei}: schon verarbeitet am {state[h].get('am')}. Übersprungen (--nochmal erzwingt).")
            continue
        reader = PdfReader(str(pdf))
        stempel = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        archiv_ziel = p.archiv / f"{stempel}_{datei}"
        print(f"{datei}\n  Archiv: {archiv_ziel.relative_to(p.basis)}")
        if not trocken:
            def kopiere(f, quelle=pdf):
                with open(quelle, "rb") as q:
                    shutil.copyfileobj(q, f)
            archiv_ziel = schreibe_neu(archiv_ziel, kopiere)
            if sha256(archiv_ziel) != h:
                print("  FEHLER: Archivkopie weicht ab. Abbruch dieses Scans.")
                return 2
        erzeugt = []
        for z in docs:
            ziel_ordner = p.post / z["ziel"]
            ziel = ziel_ordner / z["name"]
            print(f"  S.{z['seiten']} -> Post/{z['ziel']}/{z['name']}")
            if trocken:
                continue

            def schreibe(f, seiten=z["seiten"]):
                w = PdfWriter()
                for nr in seiten:
                    w.add_page(reader.pages[nr - 1])
                w.write(f)
            fertig = schreibe_neu(ziel, schreibe)
            if len(PdfReader(str(fertig)).pages) != len(z["seiten"]):
                print(f"  FEHLER: {fertig.name} hat falsche Seitenzahl. Abbruch.")
                return 2
            erzeugt.append(str(fertig.relative_to(p.basis)))
            rel = str(fertig.relative_to(p.post))
            n_fr = fristen_neu_anlegen(p, z, regeln, rel)
            fr_text = "; ".join(f"{f.get('datum') or 'ohne Datum'} {f.get('art','')}".strip() for f in z["fristen"])
            seiten_txt = ",".join(str(x) for x in z["seiten"])
            haenge_zeile_an(p.protokoll, PROTOKOLL_KOPF,
                            [jetzt(), datei, seiten_txt, fertig.name, z["ziel"], fr_text, z["hinweis"]])
        weg = [w for sc in plan["scans"] if sc["datei"] == datei for w in sc.get("weggelassen", [])]
        if weg and not trocken:
            haenge_zeile_an(p.protokoll, PROTOKOLL_KOPF,
                            [jetzt(), datei, ",".join(str(w["seite"]) for w in weg), "(weggelassen)", ARCHIV,
                             "", "Seiten weggelassen: " + ", ".join(f"{w['seite']}={w['grund']}" for w in weg)])
        if not trocken:
            state[h] = {"am": jetzt(), "datei": datei, "archiv": str(archiv_ziel.relative_to(p.basis)), "ergebnis": erzeugt}
            speichere_state(p, state)
            if a.eingang_aufraeumen:
                ordner = p.eingang / "_erledigt"
                ordner.mkdir(exist_ok=True)
                ziel_alt = freier_pfad(ordner / datei)
                shutil.move(str(pdf), str(ziel_alt))
                print(f"  Eingang: verschoben nach {ziel_alt.relative_to(p.basis)}")
    if not trocken:
        schreibe_ansicht(p, heute(a))
        print(f"\nFristen-Ansicht neu erzeugt: {p.fristen_ansicht.relative_to(p.basis)}")
    return 0


def tage_text(t: int) -> str:
    if t < 0:
        return f"seit {-t} Tagen überfällig"
    if t == 0:
        return "HEUTE"
    return f"in {t} Tagen"


def schreibe_ansicht(p: Pfade, heute_: dt.date) -> None:
    """Erzeugt die sortierte Fristen-Ansicht neu. Ist eine abgeleitete Datei, kein Original."""
    erledigt = {r["id"] for r in lies_csv(p.fristen_erledigt)}
    offen = [r for r in lies_csv(p.fristen_daten) if r["id"] not in erledigt]
    gruppen = {"ÜBERFÄLLIG": [], "DRINGEND (bis 7 Tage)": [], "BALD (bis 30 Tage)": [], "SPÄTER": [], "OHNE DATUM": []}
    for r in offen:
        if not r["datum"]:
            gruppen["OHNE DATUM"].append((None, r))
            continue
        d = dt.date.fromisoformat(r["datum"])
        t = (d - heute_).days
        key = "ÜBERFÄLLIG" if t < 0 else "DRINGEND (bis 7 Tage)" if t <= 7 else "BALD (bis 30 Tage)" if t <= 30 else "SPÄTER"
        gruppen[key].append((t, r))
    zeilen = [f"# Offene Fristen (Stand {heute_.strftime('%d.%m.%Y')})", "",
              "Diese Datei wird bei jedem Lauf neu erzeugt. Die Quelle ist `_Fristen_Daten.csv`.",
              "Erledigtes eintragen: `pipeline.py erledigt <id>`.", ""]
    for name, liste in gruppen.items():
        if not liste:
            continue
        zeilen += [f"## {name} ({len(liste)})", "", "| Wann | Datum | Art | Betrag | Von | Worum | Datei | id |", "|---|---|---|---|---|---|---|---|"]
        for t, r in sorted(liste, key=lambda x: (x[0] is None, x[0] if x[0] is not None else 0)):
            wann = tage_text(t) if t is not None else "-"
            dat = dt.date.fromisoformat(r["datum"]).strftime("%d.%m.%Y") if r["datum"] else "-"
            if r["status"] == "berechnet" and r["datum"]:
                dat += " (berechnet)"
            betrag = f"{r['betrag']} EUR" if r["betrag"] else "-"
            zeilen.append(f"| {wann} | {dat} | {r['art']} | {betrag} | {r['absender']} | {r['betreff']} | {r['datei']} | {r['id']} |")
        zeilen.append("")
    if len(zeilen) <= 5:
        zeilen.append("Keine offenen Fristen.")
    p.fristen_ansicht.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def cmd_bekannt(a, p: Pfade, regeln: dict) -> int:
    """Markiert Scans im Eingang als schon erledigt, ohne etwas abzulegen.
    Gedacht für einmaliges Einrichten, wenn alte Scans im Eingang liegen."""
    state = lade_state(p)
    n = 0
    for pdf in scans_im_eingang(p):
        h = sha256(pdf)
        if h in state:
            continue
        if a.dateien and pdf.name not in a.dateien:
            continue
        state[h] = {"am": jetzt(), "datei": pdf.name, "archiv": "", "ergebnis": [], "hinweis": "als bekannt markiert"}
        n += 1
        print(f"bekannt: {pdf.name}")
    speichere_state(p, state)
    print(f"{n} Scans als bekannt markiert.")
    return 0


def cmd_fristen(a, p: Pfade, regeln: dict) -> int:
    schreibe_ansicht(p, heute(a))
    print(p.fristen_ansicht.read_text(encoding="utf-8"))
    return 0


def cmd_erledigt(a, p: Pfade, regeln: dict) -> int:
    ids = {r["id"] for r in lies_csv(p.fristen_daten)}
    for i in a.ids:
        if i not in ids:
            print(f"id {i} gibt es nicht.")
            return 1
    for i in a.ids:
        haenge_zeile_an(p.fristen_erledigt, ERLEDIGT_KOPF, [i, heute(a).isoformat(), a.notiz or ""])
    schreibe_ansicht(p, heute(a))
    print(f"{len(a.ids)} als erledigt eingetragen.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basis", help="Dropbox-Ordner (mit 00 ScanEingang). Sonst automatisch.")
    ap.add_argument("--regeln", help="Pfad zu regeln.json")
    ap.add_argument("--heute", help="Testdatum JJJJ-MM-TT")
    sub = ap.add_subparsers(dest="befehl", required=True)
    sub.add_parser("status", help="Neue Scans im Eingang anzeigen")
    e = sub.add_parser("extract", help="Seiten lesen und Entwurf machen")
    e.add_argument("--alle", action="store_true", help="auch schon verarbeitete Scans")
    e.add_argument("--zeichen", type=int, default=260, help="Textlänge je Seite im Auszug")
    z = sub.add_parser("zeige", help="Volltext einzelner Seiten")
    z.add_argument("datei")
    z.add_argument("seiten", nargs="*", type=int)
    v = sub.add_parser("validate", help="Plan prüfen, nichts ändern")
    v.add_argument("--plan")
    ap_ = sub.add_parser("apply", help="Plan ausführen")
    ap_.add_argument("--plan")
    ap_.add_argument("--ja", action="store_true", help="wirklich ausführen (sonst Trockenlauf)")
    ap_.add_argument("--nochmal", action="store_true", help="auch schon verarbeitete Scans")
    ap_.add_argument("--eingang-aufraeumen", action="store_true", help="Original in 00 ScanEingang/_erledigt verschieben")
    b = sub.add_parser("bekannt", help="Scans im Eingang als schon erledigt markieren (einmalig)")
    b.add_argument("dateien", nargs="*", help="nur diese Dateien, sonst alle im Eingang")
    sub.add_parser("fristen", help="Fristen-Ansicht neu erzeugen und zeigen")
    er = sub.add_parser("erledigt", help="Frist als erledigt eintragen")
    er.add_argument("ids", nargs="+")
    er.add_argument("--notiz")
    a = ap.parse_args()
    p = Pfade(finde_basis(a.basis))
    regeln = lade_regeln(a.regeln, p)
    return {"status": cmd_status, "extract": cmd_extract, "zeige": cmd_zeige, "validate": cmd_validate,
            "apply": cmd_apply, "fristen": cmd_fristen, "erledigt": cmd_erledigt,
            "bekannt": cmd_bekannt}[a.befehl](a, p, regeln)


if __name__ == "__main__":
    sys.exit(main())
