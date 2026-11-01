# Post abarbeiten: Anleitung für Claude

Das gilt für jeden Scan, egal was drin ist.
Du urteilst. Das Skript `pipeline.py` prüft und führt aus.

Befehl (findet Dropbox selbst):
```
uv run --with pypdf python <Ordner>/pipeline.py <befehl>
```
Der Ordner ist `Post/_System/` in Dropbox oder `post/` im Repo.

## Ablauf

1. **`status`**: Zeigt neue Scans im Eingang.
2. **`extract`**: Liest jede Seite. Schreibt `arbeit/extract.json` und einen gültigen `arbeit/plan_entwurf.json`.
   - Marker zeigen "Seite x von y". Rückwärts gescannte Stapel erkennt das Skript.
   - `LEER` heißt keine Zeichen. `WENIG` heißt fast leer, aber Text. Prüfen, nicht weglassen.
   - `zeige <datei> <seite...>` zeigt den ganzen Text einer Seite.
3. **Urteilen.** Pro Scan:
   - Welche Seiten gehören zu einem Schreiben? In welcher Reihenfolge?
   - Absender, Betreff, Datum des Schreibens (nicht Scandatum), Zielordner aus `regeln.json`.
   - Fristen suchen (siehe unten).
4. **`plan.json` schreiben** in `arbeit/` (Schema unten).
5. **`validate`**: Prüft den Plan. Zeigt die Tabelle. Ändert nichts.
6. **Tabelle zeigen und auf "ok" warten.** Ausnahme: Manuel sagte "ab jetzt automatisch" und die Sicherheit ist über 95 %.
7. **`apply`** (Trockenlauf), dann **`apply --ja`**.
8. **Zusammenfassung** auf Deutsch: wie viele Dokumente, wohin, neue Fristen, To-dos, was in `99_Unklar` liegt.

## Schema von plan.json

```json
{"scans": [{
  "datei": "01112026135702.pdf",
  "sha256": "(aus extract.json übernehmen)",
  "dokumente": [{
    "seiten": [4, 3, 2, 1],
    "datum": "2026-09-07",
    "absender": "Green-Planet-Energy",
    "betreff": "Schlussrechnung-Strom",
    "ziel": "10_Privat/Wohnen",
    "sicherheit": 0.9,
    "bestaetigt": false,
    "fristen": [{"datum": "2026-10-23", "art": "Zahlung", "betrag": "257,47", "status": "genannt"}]
  }],
  "weggelassen": [{"seite": 5, "grund": "leer"}]
}]}
```
- `seiten` stehen in Lesereihenfolge.
- Jede Seite kommt genau einmal vor, in `dokumente` oder `weggelassen`.
- `grund` ist `leer` oder `doppelt`. Eine Seite mit Text wird abgelehnt.
- `status` ist `genannt` (steht im Brief) oder `berechnet` (du hast gerechnet).
- `bestaetigt: true` nur, wenn Manuel die Zuordnung bestätigt hat. Sonst gilt unter 80 % automatisch `99_Unklar`.

## Regeln fürs Urteilen

- Es zählt, **wen oder was** das Schreiben betrifft, nicht nur der Adressat.
- Lüneburg läuft privat, Lübeck über die Holi Grounds GmbH. Nie verwechseln.
- Unter ca. 80 % sicher: nach `99_Unklar` und Manuel fragen.
- Keine Bank-, Konto-, Steuer- oder Ausweisnummern in Namen, Fristen oder Protokoll. Das Skript lehnt sie ab.
- Dateiname: `JJJJ-MM-TT_Absender_Betreff.pdf`. Das Skript baut ihn, du lieferst die Teile.
- Kein Text auf allen Seiten: ein Dokument mit allen Seiten, Ziel `99_Unklar`, Betreff `Scan-ohne-Text-ungeteilt`. OCR ist auf dem Intel-Mac nicht da.

## Fristen finden

Suche: Zahlungsziel, Fälligkeit, "innerhalb von", "bis zum", Widerspruch, Einspruch, Kündigung, Termin, Stellungnahme.
- Einspruch: 1 Monat ab Bekanntgabe. Bei einfachem Brief gilt der 4. Tag nach Datum als Bekanntgabe.
- Anhörung Bußgeld: 1 Woche.
- Relative Fristen rechnest du aus. Als Zugang gilt das Scandatum. `status` ist dann `berechnet`.
- Frist-Art: Zahlung, Einspruch, Widerspruch, Stellungnahme, Kuendigung, Termin, Unterlagen, Sonstiges.
- Das Skript schreibt `_Fristen_Daten.csv` und erzeugt `_Fristen_Aktuell.md` neu. Überfälliges steht ganz oben.
- Erledigt: `erledigt <id> --notiz "bezahlt"`.

## Nach einem Fehler oder einer Korrektur

- Manuel korrigiert eine Zuordnung? Frag, ob daraus eine Regel werden soll. Dann einen Block in `regeln.json` unter `zuordnung` ergänzen.
- Neuer Ordner nötig? In `ziele` eintragen und den Ordner anlegen lassen. Das Skript legt nur Ordner aus dieser Liste an.

## Einmalig beim Einrichten

Liegen schon erledigte Scans im Eingang, einmal `bekannt` laufen lassen. Dann werden sie nicht doppelt abgelegt.

## Was nie passiert

Löschen, Überschreiben, Senden, Bezahlen. Das Original im Eingang bleibt, außer `--eingang-aufraeumen` (verschiebt nach `_erledigt`, löscht nicht).
