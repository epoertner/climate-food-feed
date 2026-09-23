# Climate & Food Critical Feed

Four RSS feeds for NetNewsWire, generated weekly from a multilingual research-and-curation pipeline.

## Feeds

- `feeds/climate.xml` — Climate & Ecology
- `feeds/agriculture.xml` — Agriculture & Food Systems
- `feeds/switzerland.xml` — Switzerland
- `feeds/crossovers.xml` — Crossovers / Wild Cards

After GitHub Pages is enabled, the feeds will be available under:

`https://YOUR-USER.github.io/climate-food-critical-feed/feeds/climate.xml`

(and similarly for the other three files).

## Editorial specification

The curator is instructed to:

- cover English, German and French;
- select for surprise, counter-intuitive findings, critical analysis, new evidence,
  important blind spots and unexpected connections;
- avoid ranking by outlet size, prestige or audience;
- keep scientific sources at roughly 50% or more of the overall selection;
- explicitly scan critical social-science and agrarian journals, not only Nature/Science;
- aim for roughly one third of all selected items to have a substantive Switzerland
  connection, without padding the quota when quality is insufficient;
- prefer original research, systematic reviews, scholarly syntheses, investigative
  journalism and substantive NGO/think-tank reports;
- avoid press releases, shallow opinion pieces and routine daily news;
- allow older publications when a new development makes them newly relevant.

Scientific coverage includes, among others:

Antipode, Political Geography, Environment and Planning A-E, Geoforum,
Global Environmental Change, Ecological Economics, Journal of Peasant Studies,
Journal of Agrarian Change, Agriculture and Human Values, Food Policy,
Sociologia Ruralis, Third World Quarterly, Nature Food, Nature Climate Change,
One Earth, Environmental Research Letters and relevant adjacent fields.

## Setup

### 1. Create a GitHub repository

Create a public repository named:

`climate-food-critical-feed`

Upload this project.

### 2. Add an OpenAI API key

In GitHub:

Settings → Secrets and variables → Actions → New repository secret

Create:

`OPENAI_API_KEY`

The workflow uses the key only in GitHub Actions. It is never written into the repository.

### 3. Enable GitHub Pages

Settings → Pages → Build and deployment → Source: GitHub Actions.

### 4. Optional: add more source feeds

Edit:

`src/sources.yml`

The pipeline already performs web discovery, so this is a seed list rather than a complete whitelist.

### 5. Run it

Actions → Weekly Feed Update → Run workflow.

The scheduled run is Monday morning, Europe/Zurich.

## Important

The generated RSS files are intentionally static. NetNewsWire only needs to fetch the XML.

The research/curation happens in GitHub Actions. The model is instructed to return source URLs and concise editorial explanations, but the pipeline also stores the selection in `data/archive.json` so previously used items can be avoided.

## Local test

Python 3.11+:

```bash
pip install -r requirements.txt
python src/generate_feed.py
```

Without `OPENAI_API_KEY`, the script performs a dry run and creates valid empty feeds plus diagnostics. For the real curation run, set the key.
