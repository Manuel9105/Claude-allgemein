#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Selbsttest der Post-Pipeline. Arbeitet nur in einem Temp-Ordner, nie in deiner Dropbox.

Aufruf: uv run --with pypdf --with reportlab python post/selbsttest.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader
from reportlab.pdfgen import canvas

HIER = Path(__file__).resolve().parent
PIPE = HIER / "pipeline.py"
fehler = []


def pdf(pfad, seiten):
    c = canvas.Canvas(str(pfad))
    for zeilen in seiten:
        y = 800
        for z in zeilen:
            c.drawString(50, y, z)
            y -= 18
        c.showPage()
    c.save()


def lauf(basis, *args):
    env = dict(os.environ, POST_BASIS=str(basis))
    r = subprocess.run([sys.executable, str(PIPE), "--heute", "2026-11-01", *args], env=env,
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def pruefe(name, bedingung, info=""):
    print(("OK      " if bedingung else "FEHLER  ") + name + (f"  {info}" if not bedingung and info else ""))
    if not bedingung:
        fehler.append(name)


with tempfile.TemporaryDirectory() as t:
    basis = Path(t)
    eingang = basis / "00 ScanEingang"
    eingang.mkdir()
    (basis / "01_Archiv-Original").mkdir()
    (basis / "Post").mkdir()
    pdf(eingang / "a.pdf", [
        ["Seite 3 von 3", "Hinweise Green Planet Energy"],
        ["Seite 2 von 3", "Verbrauch 1.037,90 EUR"],
        ["Green Planet Energy", "Hamburg, den 07.09.2026", "Sehr geehrter Herr Kappernagel,", "Schlussrechnung Strom", "Seite 1 von 3"],
        [" "],
        ["Hansestadt Lübeck", "Hamburg, den 09.10.2026", "Sehr geehrte Damen und Herren,", "MAHNUNG Grundsteuer B", "bis 23.10.2026 257,47 EUR"],
    ])
    pdf(eingang / "b.pdf", [[" "], [" "]])

    rc, out = lauf(basis, "extract")
    pruefe("extract läuft", rc == 0, out)
    arbeit = basis / "Post" / "_System" / "arbeit"
    ex = json.loads((arbeit / "extract.json").read_text(encoding="utf-8"))
    a = next(s for s in ex["scans"] if s["datei"] == "a.pdf")
    pruefe("Rückwärts-Seiten werden geordnet", a["vorschlag"]["dokumente"][0]["seiten"] == [3, 2, 1])
    pruefe("Leerseite erkannt", a["vorschlag"]["leer"] == [4])
    pruefe("Scan ohne Text erkannt", next(s for s in ex["scans"] if s["datei"] == "b.pdf")["ocr_noetig"])

    plan = json.loads((arbeit / "plan_entwurf.json").read_text(encoding="utf-8"))
    (arbeit / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    rc, out = lauf(basis, "validate")
    pruefe("Entwurf ist gültig", rc == 0, out)
    rc, out = lauf(basis, "apply")
    pruefe("Trockenlauf schreibt nichts", not list((basis / "Post").glob("10_Privat")) and not list((basis / "01_Archiv-Original").iterdir()))

    plan["scans"][0]["dokumente"][1]["fristen"] = [{"datum": "2026-10-23", "art": "Zahlung", "betrag": "257,47", "status": "genannt"}]
    (arbeit / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    rc, out = lauf(basis, "apply", "--ja")
    pruefe("apply --ja läuft", rc == 0, out)
    pruefe("Archiv hat beide Originale", len(list((basis / "01_Archiv-Original").iterdir())) == 2)
    ziel = list((basis / "Post" / "40_Holi-Grounds-GmbH").rglob("*Mahnung*.pdf"))
    pruefe("Mahnung am richtigen Ort", len(ziel) == 1)
    strom = list((basis / "Post").rglob("*Green-Planet*.pdf")) + list((basis / "Post" / "99_Unklar").glob("*Green*"))
    pruefe("Strom abgelegt, 3 Seiten", strom and len(PdfReader(str(strom[0])).pages) == 3)
    pruefe("Original im Eingang unverändert", (eingang / "a.pdf").exists() and (eingang / "b.pdf").exists())
    pruefe("Protokoll angelegt", (basis / "Post" / "_Protokoll.csv").read_text(encoding="utf-8").count("\n") >= 3)
    pruefe("Fristen-Ansicht hat Überfälliges", "ÜBERFÄLLIG" in (basis / "Post" / "_Fristen_Aktuell.md").read_text(encoding="utf-8"))
    rc, out = lauf(basis, "apply", "--ja")
    pruefe("zweiter Lauf überspringt", "Übersprungen" in out, out)

    pdf(eingang / "c.pdf", [["Hansestadt Lübeck", "Hamburg, den 09.10.2026", "Sehr geehrte Damen und Herren,", "MAHNUNG Grundsteuer B"]])
    lauf(basis, "extract")
    plan = json.loads((arbeit / "plan_entwurf.json").read_text(encoding="utf-8"))
    d = plan["scans"][0]["dokumente"][0]
    d.update(datum="2026-10-09", absender="Hansestadt-Luebeck", betreff="Mahnung", sicherheit=0.9)
    (arbeit / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    lauf(basis, "apply", "--ja")
    namen = sorted(p.name for p in (basis / "Post" / "40_Holi-Grounds-GmbH").rglob("*Mahnung*.pdf"))
    pruefe("gleicher Name wird _2, nichts überschrieben", len(namen) == 2 and any(n.endswith("_2.pdf") for n in namen), str(namen))

    schlecht = json.loads(json.dumps(plan))
    schlecht["scans"][0]["dokumente"][0]["seiten"] = []
    (arbeit / "plan.json").write_text(json.dumps(schlecht), encoding="utf-8")
    pruefe("fehlende Seite wird abgelehnt", lauf(basis, "validate")[0] == 1)
    schlecht = json.loads(json.dumps(plan))
    schlecht["scans"][0]["dokumente"][0]["betreff"] = "DE53 2304 0022 0035 8507 00"
    (arbeit / "plan.json").write_text(json.dumps(schlecht), encoding="utf-8")
    pruefe("IBAN wird abgelehnt", lauf(basis, "validate")[0] == 1)
    schlecht = json.loads(json.dumps(plan))
    schlecht["scans"][0]["dokumente"][0]["ziel"] = "../../irgendwo"
    (arbeit / "plan.json").write_text(json.dumps(schlecht), encoding="utf-8")
    pruefe("Ziel ausserhalb wird abgelehnt", lauf(basis, "validate")[0] == 1)
    schlecht = json.loads(json.dumps(plan))
    schlecht["scans"][0]["dokumente"] = []
    schlecht["scans"][0]["weggelassen"] = [{"seite": 1, "grund": "leer"}]
    (arbeit / "plan.json").write_text(json.dumps(schlecht), encoding="utf-8")
    pruefe("Seite mit Text darf nicht als leer weggelassen werden", lauf(basis, "validate")[0] == 1)

print()
if fehler:
    print(f"{len(fehler)} Fehler: {fehler}")
    sys.exit(1)
print("Alles in Ordnung.")
