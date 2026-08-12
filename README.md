# Konferenz Book of Contents

Statische Website (GitHub Pages) + PDF-Abstractband, automatisch erzeugt aus
Daten, die du aus einem Google Form / Sheet exportierst und ins Repo legst.
Der Code selbst kennt keine Konferenz-Details — alles Konferenzspezifische
lebt in `config.yml` und in `data/`, siehe [Für eine andere Konferenz
wiederverwenden](#für-eine-andere-konferenz-wiederverwenden).

(Automatischer Mailversand ist bewusst noch nicht enthalten – lässt sich
später ergänzen.)

## Funktionsweise

```
Google Form  →  Sheet  →  xlsx exportieren  →  data/*.xlsx ins Repo committen
                                                      │
                          GitHub Action (bei Push + manuell):
                            1. Einreichungen einlesen, nach Session gruppieren
                            2. index.html (Web, DE+EN) + Book-of-Contents-PDFs rendern
                            3. auf GitHub Pages deployen
```

Es wird nichts Generiertes committet: die Seite wird als Pages-Artefakt
deployt. Versioniert werden nur die Rohdaten in `data/`.

## Dateien

- `config.yml` – Konferenzdaten, Datei-Pfade, Zuordnung Spalten → Felder, i18n-Texte
- `scripts/build.py` – Daten einlesen, rendern (Web + PDF)
- `scripts/export_emails.py` – lokales Hilfsskript, siehe [E-Mail-Liste](#e-mail-liste-lokal-exportieren)
- `templates/` – Web- und PDF-Vorlage (Jinja2), sprachunabhängig — DE und EN
  laufen durch dieselben Templates, ein Layout-Fix gilt also automatisch für
  beide Sprachen
- `.github/workflows/build.yml` – Build + Deployment

### Daten (`data/`)

| Datei (Standardname, per `config.yml` änderbar) | Zweck |
|---|---|
| `FANT26_merged.xlsx` (`input.xlsx_path`) | Einreichungen (Titel, Autor:innen, Abstract, …). Primärquelle; `input.csv_path` ist der Fallback, falls die xlsx fehlt. |
| `FANT26_schedule.xlsx` (`input.schedule_xlsx_path`) | Zeitplan. Optional — fehlt die Datei, wird der Programmabschnitt einfach nicht gerendert. Sheet `Schedule` (Spalten `Module`, `Time`) plus optional `Presenters` (`Last name`, `First name`, `Topic`, `Session`), um Vortragende einem Programmpunkt zuzuordnen. |
| `intro.html.docx` (`input.intro_docx_path`) | Einleitungstext, DE. Wird beim Build automatisch per mammoth in HTML konvertiert. |
| `location.docx` (`input.location_docx_path`) | Anfahrt/Ort-Text, DE. Gleiches Prinzip. |
| `intro-en.html`, `location-en.html` | Handübersetzte englische Fassungen der obigen Texte. |
| `intro.html`, `location-de.html` | Fallback, falls die jeweilige `.docx` mal fehlt/nicht lesbar ist. |
| `logo.png` (`conference.logo_path`) | Logo in Header (Web) und PDF. Optional. |

Alle Pfade in der Tabelle sind Standardwerte aus `config.yml` — Dateien
können beliebig heißen, solange `config.yml` darauf zeigt.

Neuer Text-Block gewünscht (z. B. "Call for Papers")? Einfach eine weitere
`.docx` + optionale `-en.html`-Übersetzung anlegen und in `build.py`/den
Templates nach demselben Muster wie `intro`/`location` verdrahten
(`load_text_block()` in `scripts/build.py` ist dafür gedacht).

## Einrichtung

### 1. Einreichungsdaten ablegen

1. Google Form → verknüpftes Sheet öffnen.
2. Datei → Herunterladen → **xlsx** (oder CSV, falls kein xlsx gewünscht).
3. Datei nach `data/` legen, Pfad in `config.yml → input.xlsx_path`
   (bzw. `csv_path`) eintragen, committen.

> **Datenschutz:** Bei einem *öffentlichen* Repo sind alle Dateien in
> `data/` öffentlich, inklusive Versionshistorie. Titel/Autor:innen/Abstracts
> ist i. d. R. gewollt – aber **E-Mail-Adressen gehören nicht hinein**.
> Vor dem ersten Commit prüfen, ob das Form eine E-Mail-Spalte mitexportiert,
> und diese Spalte löschen (oder das Repo privat halten). Für den eigenen
> Gebrauch siehe [E-Mail-Liste lokal exportieren](#e-mail-liste-lokal-exportieren).

### 2. config.yml anpassen

- `input.columns` **exakt** auf die Spaltenüberschriften (Zeile 1) mappen.
  Falsche Zuordnung = leere Felder im Abstractband. Nicht erhobene Felder als
  `""` lassen.
- Konferenz-Metadaten (`conference:`), Datei-Pfade (`input:`) und
  `session_order` setzen.

### 3. GitHub Pages aktivieren

Repo → Settings → Pages → **Source: GitHub Actions**.
`config.yml → conference.site_url` auf die angezeigte Pages-URL setzen.

### 4. Workflow auslösen

- Automatisch bei jedem Push, der `data/`, `templates/`, `scripts/` oder
  `config.yml` ändert (also auch beim Hochladen neuer Einreichungsdaten).
- Oder manuell: Actions-Tab → "Build Book of Contents" → "Run workflow".

## Lokal testen

```bash
pip install -r requirements.txt
# WeasyPrint braucht Pango/Cairo (Linux):
#   sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0
python scripts/build.py
# Ergebnis: site/index.html, site/index-en.html, site/book_of_contents_de.pdf, site/book_of_contents_en.pdf
```

WeasyPrint (PDF-Rendering) braucht Pango/Cairo-Systembibliotheken, die unter
Windows nicht ohne Weiteres verfügbar sind — auf Windows lässt sich der
HTML-Teil trotzdem lokal testen (Jinja-Template direkt rendern, ohne den
`WPHtml`-Aufruf in `render()`), der PDF-Teil läuft zuverlässig nur unter
Linux/CI.

## E-Mail-Liste lokal exportieren

```bash
python scripts/export_emails.py
# Ergebnis: data/emails.txt (eine Zeile, Semikolon-getrennt)
```

Liest die `Email address`-Spalte aus der Einreichungsdatei, dedupliziert
und schreibt eine einzeilige, semikolon-getrennte Liste zum Einfügen in ein
Mail-Programm (z. B. Horde: An/BCC-Feld). `data/emails.txt` ist in
`.gitignore` eingetragen und wird **nie** committet — dieses Repo ist
öffentlich, eine E-Mail-Liste hat da nichts zu suchen.

## Für eine andere Konferenz wiederverwenden

`scripts/` und `templates/` sind komplett konferenz-unabhängig. Für eine
neue Konferenz:

1. Repo (oder nur `data/`-Inhalt + `config.yml`) für die neue Konferenz
   zurücksetzen: alte `data/*.xlsx`, `*.docx`, `*.csv`, `logo.png` durch die
   neuen Dateien ersetzen (Namen sind egal, siehe Tabelle oben).
2. `config.yml` komplett durchgehen: `conference:` (Titel, Datum, Ort,
   Kartenkoordinaten, Logo-Pfad, Pages-URL), `input:` (Datei-Pfade,
   Spalten-Mapping), `session_order`, `i18n:` (Track-Namen, UI-Texte je
   Sprache — Sprachen hinzufügen/entfernen geht durch Hinzufügen/Entfernen
   von Blöcken unter `i18n:`).
3. Fertig — `scripts/build.py` und die Templates müssen nicht angefasst
   werden, solange die Struktur der Einreichungsdaten (Titel, Autor:in,
   Abstract, …) grundsätzlich gleich bleibt.

## Später: automatischer Mailversand

Vorgesehen, aber noch nicht gebaut. Sinnvollster Weg, sobald gewünscht:
ein kleines Google-Apps-Script am Sheet, das bei jeder Einreichung sofort eine
Bestätigung schickt – unabhängig vom hier beschriebenen Website-Build.
