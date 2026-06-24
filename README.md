# Konferenz Book of Contents

Statische Website (GitHub Pages) + PDF-Abstractband, automatisch erzeugt aus
einer CSV, die du aus dem Google Form / Sheet exportierst und ins Repo legst.

(Automatischer Mailversand ist bewusst noch nicht enthalten – lässt sich
später ergänzen.)

## Funktionsweise

```
Google Form  →  Sheet  →  CSV exportieren  →  data/responses.csv ins Repo committen
                                                      │
                          GitHub Action (bei Push + manuell):
                            1. CSV einlesen, nach Session gruppieren
                            2. index.html (Web) + book_of_contents.pdf rendern
                            3. auf GitHub Pages deployen
```

Es wird nichts Generiertes committet: die Seite wird als Pages-Artefakt
deployt. Einzige versionierte Datenquelle ist die CSV.

## Dateien

- `config.yml` – Konferenzdaten + Zuordnung CSV-Spalten → Felder
- `scripts/build.py` – CSV einlesen, rendern (Web + PDF)
- `templates/` – Web- und PDF-Vorlage (Jinja2)
- `.github/workflows/build.yml` – Build + Deployment
- `data/responses.sample.csv` – Beispieldaten zum Testen

## Einrichtung

### 1. CSV exportieren und ablegen

1. Google Form → verknüpftes Sheet öffnen.
2. Datei → Herunterladen → **CSV (.csv)**.
3. Datei als `data/responses.csv` ins Repo legen und committen.

> **Datenschutz:** Bei einem *öffentlichen* Repo ist die CSV öffentlich.
> Titel/Autor:innen/Abstracts ist i. d. R. gewollt – aber **E-Mail-Adressen
> gehören nicht hinein**. Entweder Repo privat halten oder die Mailspalte vor
> dem Commit löschen.

### 2. config.yml anpassen

- `input.columns` **exakt** auf die CSV-Spaltenüberschriften (Zeile 1) mappen.
  Falsche Zuordnung = leere Felder im Abstractband. Nicht erhobene Felder als
  `""` lassen.
- Konferenz-Metadaten und `session_order` setzen.

### 3. GitHub Pages aktivieren

Repo → Settings → Pages → **Source: GitHub Actions**.
`config.yml → site_url` auf die angezeigte Pages-URL setzen.

### 4. Workflow auslösen

- Automatisch bei jedem Push, der `data/`, `templates/`, `scripts/` oder
  `config.yml` ändert (also auch beim Hochladen einer neuen CSV).
- Oder manuell: Actions-Tab → "Build Book of Contents" → "Run workflow".

## Lokal testen

```bash
pip install -r requirements.txt
# WeasyPrint braucht Pango/Cairo (Linux):
#   sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0
python scripts/build.py --csv data/responses.sample.csv
# Ergebnis: site/index.html und site/book_of_contents.pdf
```

## Später: automatischer Mailversand

Vorgesehen, aber noch nicht gebaut. Sinnvollster Weg, sobald gewünscht:
ein kleines Google-Apps-Script am Sheet, das bei jeder Einreichung sofort eine
Bestätigung schickt – unabhängig vom hier beschriebenen Website-Build.
