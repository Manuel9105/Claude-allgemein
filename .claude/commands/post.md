---
description: Neue Scans sortieren, ablegen und Fristen erfassen (lokal auf dem Mac)
---
Arbeite die neue Post ab. Befolge `post/ANLEITUNG.md`. Der Ablauf ist immer gleich.

1. `status`, dann `extract`. Lies `extract.json` und `plan_entwurf.json`.
2. Urteile pro Scan: Seiten gruppieren, ordnen, einordnen, Fristen lesen.
3. Schreibe `plan.json`, führe `validate` aus, zeige mir die Tabelle.
4. Warte auf mein "ok". Dann `apply`, dann `apply --ja`.
5. Fasse zusammen: Ablage, neue Fristen, To-dos, `99_Unklar`.

Befehl: `uv run --with pypdf python <Ordner>/pipeline.py <befehl>`. Das Skript liegt in `Post/_System/` (Dropbox) oder in `post/` (Repo).

Wichtig:
- Läuft diese Session nicht auf meinem Mac (kein Dropbox-Ordner, kein `uv`), sag das sofort.
- Nie löschen, nie überschreiben, nichts versenden.
- Unsicher heißt `99_Unklar` und fragen.
