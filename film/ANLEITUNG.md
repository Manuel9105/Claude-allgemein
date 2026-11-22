# Filmschnitt-Setup: Kinderfilm im Abenteuer-Stil

Du ziehst Szenen rein. Claude macht daraus einen Kinofilm.
Look, Musik, Effekte, Titel: alles im Geist von Kinder-Abenteuerfilmen (Typ „Die wilden Kerle“).
Alles ist **original gebaut**. Keine Originalmusik, keine Originalschrift, keine fremden Rechte.

## So läuft es

1. Szenen in `film/szenen/` legen (mp4, mov, m4v, mkv). Reihenfolge = Dateiname (`01_...`, `02_...`).
2. `/film` sagen. Claude arbeitet selbstständig.
3. Claude zeigt dir den Plan (Regie) als Tabelle. Du sagst „ok“ oder korrigierst.
4. Erst eine **Vorschau** (720p, schnell). Dann der **Final-Film** (1080p).
5. Ergebnis liegt in `film/ausgabe/`. Jede Version bekommt eine neue Nummer. Nichts wird überschrieben.

Läuft nur lokal oder in einer Session, in der die Dateien liegen. Braucht `ffmpeg` und `uv`.
Mac: `brew install ffmpeg`.

## Was Claude macht

| Bereich | Was passiert |
|---|---|
| **Look** | Warmer Abenteuer-Look: S-Kurve, goldene Lichter, kühle Schatten, Glow, Vignette, Filmkorn, Schärfe |
| **Kino-Format** | 2,39:1 mit Balken. Hochkant-Clips bekommen unscharfen Rand statt schwarzer Seiten |
| **Bewegung** | Sanfter Push-in oder Pull-out, Kamerawackeln bei Knallen, Zeitlupe mit Ton-Absenkung |
| **Effekte** | Lichtblitze, schwebender Staub, Glut, Zauberfunken (Partikel, nahtlos geloopt) |
| **Übergänge** | Kreisblende, Zoom, Wisch, Weißblende, Schwarzblende. Je nach Stimmung gewählt |
| **Titel** | Großer Goldtitel mit Knall, Kapitel-Einblendungen, scrollender Abspann |
| **Musik** | Original komponiert: Heldenthema, Taiko-Trommeln, Streicher, Blech. 7 Stimmungen |
| **Effekt-Sounds** | Whoosh, Boom, Riser, Funkeln, Zauber, Fanfare, Herzschlag, Grollen, Pop |
| **Ton** | Rauschen raus, Stimmen klar, Musik duckt automatisch unter Sprache, Lautheit -16 LUFS |

## Stimmungen

`intro` · `abenteuer` · `action` · `spannung` · `ruhig` · `sieg` · `abspann`

Jede Stimmung bringt Look, Kamerabewegung, Partikel, Übergänge und Musik mit.
Feinschliff in `film/stil.json`. Dort drehst du den Look, nicht im Code.

## Die Regie (`film/regie.json`)

Claude schreibt sie nach dem Ansehen der Szenen. Du kannst sie auch selbst ändern.
Zeiten gelten für die **fertige Szene** (nach Schnitt und Zeitlupe). Nur `zeitlupe` nutzt Quellzeit.

```json
{
  "titel": "DIE WILDE BANDE\nUND DER SCHATZ",
  "untertitel": "Ein Abenteuer",
  "look": "auto",
  "format": "kino",
  "vorspann": true,
  "abspann": {"zeilen": ["# Regie", "Name", "", "# Darsteller", "Name"]},
  "musik_lautstaerke": 0.55,
  "sfx_lautstaerke": 0.7,
  "szenen": [
    {
      "datei": "01_wald.mp4",
      "kapitel": "Kapitel 1 – Aufbruch",
      "stimmung": "abenteuer",
      "von": 0, "bis": 12,
      "zeitlupe": {"von": 4.0, "bis": 6.0, "faktor": 0.5},
      "wackeln": [{"bei": 8.0, "dauer": 0.6, "staerke": 1.0}],
      "blitz": [8.0],
      "sfx": [{"bei": 8.0, "art": "boom"}],
      "partikel": "staub",
      "bewegung": "push",
      "uebergang": "circleopen",
      "originalton": 1.0
    }
  ]
}
```

| Feld | Werte |
|---|---|
| `stimmung` | intro, abenteuer, action, spannung, ruhig, sieg, abspann |
| `look` | auto, abenteuer, action, nacht, dschungel, sonnig |
| `partikel` | staub, glut, funken, aus |
| `bewegung` | push, pull, keine |
| `uebergang` | fade, fadeblack, fadewhite, dissolve, circleopen, circleclose, radial, zoomin, slideleft, slideright, smoothleft, smoothright, wipeleft, wiperight, pixelize, horzopen, vertopen, schnitt |
| `sfx.art` | whoosh, whoosh_lang, boom, stinger, riser, sparkle, zauber, rumble, pop, fanfare, herzschlag |
| `musik` | Stimmung für die Musik, falls anders als das Bild. `stumm` = keine Musik |
| `originalton` | 0 bis 1.5. `0` = Ton der Szene aus |

## Befehle

Immer: `uv run --with numpy python film/kino.py <befehl>`

| Befehl | Zweck |
|---|---|
| `status` | Prüft ffmpeg, Szenen, Regie, Ausgabe |
| `analyse` | Misst jede Szene, macht Kontaktbögen (`film/arbeit/kontakt_NN.jpg`) und `regie_entwurf.json` |
| `bauen --vorschau` | Schneller 720p-Film zum Prüfen |
| `bauen` | Final 1080p |
| `bauen --nur 2,3` | Nur Szenen 2 und 3, ohne Titelkarte. Zum Probieren |
| `auto` | Analyse (falls keine Regie da ist) und bauen in einem Rutsch |
| `klang ordner` | Alle Musikstile und Effekte als WAV zum Anhören |

Selbsttest: `uv run --with numpy python film/selbsttest.py`. Baut einen Mini-Film aus Testclips.

## Eigene Wünsche

- **Eigene Musik:** Datei `film/musik/<stimmung>.mp3` (zum Beispiel `action.mp3`). Sie hat Vorrang. Nur Musik nutzen, für die du die Rechte hast.
- **Eigene Schrift:** `.ttf` oder `.otf` nach `film/assets/fonts/`. Ein wilder Grunge-Titel passt gut. Auf Lizenz achten.
- **Anderer Look:** `film/stil.json`. Neue Looks eintragen, in der Regie per Name nutzen.

## Regeln für Claude

- Originale in `szenen/` nie anfassen, nie löschen, nie verschieben.
- Ausgaben nie überschreiben. `bauen` nummeriert selbst.
- Erst Kontaktbögen ansehen (Bild lesen), dann Stimmung und Kapitel vergeben. Nicht blind dem Entwurf folgen.
- Erst Regie zeigen und auf „ok“ warten. Dann Vorschau. Dann Final.
- Namen von Kindern nur nutzen, wenn Manuel sie nennt. Nichts hochladen, nichts veröffentlichen.
- Unsicher bei Inhalt (Gesichter, Szenenfolge)? Fragen.
- Klingt oder sieht etwas falsch aus? In der Vorschau ehrlich sagen und korrigieren.

## Grenzen (ehrlich)

- Die Musik ist synthetisch. Sie klingt nach Filmmusik-Skizze, nicht nach Orchester.
  Für den echten Kino-Eindruck: eigene, lizenzfreie Musik in `film/musik/` legen.
- Eine Szene wird nicht „verstanden“. Claude sieht Kontaktbögen und urteilt. Du hast das letzte Wort.
- Zeitlupe nutzt Bildüberblendung. Das ist keine echte Hochgeschwindigkeits-Aufnahme.

## Cartoon per KI (optional, nur lokal)

Der Look `cartoon` in `stil.json` ist nur ein Filter (Konturen, flache Farben).
Für einen **echten Zeichentrick** schreibt eine Video-KI die Clips um. Das ist ein externer Dienst (Higgsfield).
Im Test hat das gut funktioniert: Modell `flux_3_video_edit`, 15 Credits für 6 Sekunden.

Ablauf (nur mit ausdrücklichem „ja“ von Manuel, es sind Aufnahmen seiner Kinder):
1. Jeden Clip auf 720p verkleinern, ohne Ton: `ffmpeg -i IN.MOV -an -vf scale=1280:-2 -r 24 -c:v libx264 -crf 22 -pix_fmt yuv420p OUT.mp4`.
2. Hochladen (`media_upload`, `curl -X PUT`, `media_confirm`). Dann `estimate_video_cost` und die Zahl nennen.
3. Umwandeln mit `generate_video`, Modell `flux_3_video_edit`, Prompt:
   „Restyle this video as a hand-drawn 2D animated cartoon like a modern children's animated feature film: bold clean outlines, flat vivid colors, soft cel shading, friendly expressive characters. Keep the motion, composition and timing exactly the same.“
4. Ergebnis laden und als `film/szenen/NN_name_cartoon.mp4` ablegen. Originale bleiben unberührt.
5. In `regie.json` für diese Szenen `"originalton"` setzen. Der KI-Clip hat keinen Ton. Der Ton muss aus dem Original kommen.
   Dafür den Originalton als Datei ziehen: `ffmpeg -i ORIGINAL.MOV -vn film/arbeit/ton_NN.wav` und mit `ffmpeg -i CARTOON.mp4 -i ton.wav -c:v copy -c:a aac -map 0:v -map 1:a` zum Clip mischen.
6. Dann normal `bauen --vorschau`. Look `auto` bleibt, der Cartoon-Clip bekommt Titel, Musik, Effekte.
Grenzen: Figuren können flackern. FLUX bearbeitet pro Clip höchstens 15 Sekunden. Längere Clips vorher teilen.
