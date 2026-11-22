---
description: Szenen aus film/szenen/ zu einem Kinderfilm im Abenteuer-Stil schneiden (Look, Musik, Effekte, Titel)
---
Schneide den Film. Befolge `film/ANLEITUNG.md`. Arbeite selbstständig, aber zeig mir die Regie vor dem Bauen.

1. `status`. Prüfe ffmpeg und die Szenen. Fehlt etwas, sag es sofort.
2. `analyse`. Lies die Tabelle. Schau dir jeden Kontaktbogen (`film/arbeit/kontakt_NN.jpg`) an.
3. Urteile pro Szene: Stimmung, Kapitel-Titel, Schnitt (`von`/`bis`), Zeitlupe, Blitz, Wackeln, Effekt-Sounds, Übergang.
   Gib dem Film einen Titel, wenn ich keinen genannt habe. Schreib alles in `film/regie.json`.
4. Zeig mir die Regie als Tabelle. Warte auf mein „ok“.
5. `bauen --vorschau`. Prüfe Länge und Schnittliste. Schau dir 3 bis 5 Einzelbilder aus dem Film an.
6. Nach meinem „ok“: `bauen` (final). Nenne mir Datei, Länge und was du geändert hast.

Befehl: `uv run --with numpy python film/kino.py <befehl>`

Wichtig:
- Originale in `film/szenen/` nie anfassen. Ausgaben nie überschreiben.
- Läuft diese Session ohne ffmpeg oder ohne die Szenen, sag das sofort.
- Nichts hochladen, nichts veröffentlichen.
- Sieht oder klingt etwas falsch? Ehrlich sagen und korrigieren, nicht schönreden.
