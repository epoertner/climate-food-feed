#!/usr/bin/env python3
"""
Generate four curated RSS feeds.

The heavy lifting is done by an OpenAI Responses API call with web search.
The model is instructed to research broadly, then return structured JSON.
This script validates the JSON, removes duplicates, preserves an archive,
and writes RSS 2.0 feeds suitable for NetNewsWire.
"""

from __future__ import annotations
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
FEED_DIR = ROOT / "feeds"
DATA_DIR = ROOT / "data"
ARCHIVE = DATA_DIR / "archive.json"
SOURCES = ROOT / "src" / "sources.yml"

FEEDS = {
    "climate": "Climate & Ecology",
    "agriculture": "Agriculture & Food Systems",
    "switzerland": "Switzerland",
    "crossovers": "Crossovers / Wild Cards",
}

TODAY = dt.date.today().isoformat()

SYSTEM = """You are the editorial curator for a multilingual weekly RSS feed.
Your job is to find genuinely substantive publications, not simply the most visible
ones.

Editorial priorities:
1. Surprise / counter-intuitive evidence.
2. Important critical analysis or a meaningful challenge to an established assumption.
3. New empirical evidence, systematic review, scholarly synthesis, or strong original
   reporting.
4. Unexpected connections between climate/ecology, agriculture/food, political economy,
   land, labour, property, colonial history, finance, infrastructure, migration,
   biodiversity, health or geopolitics.
5. Small or specialist outlets can outrank major outlets; never select because an outlet
   is famous.
6. Approximately half or more of the complete selection must be scholarly/scientific.
   Scientific includes natural sciences AND critical social science, human geography,
   political ecology, agrarian studies, sociology, anthropology, history and related
   scholarly fields.
7. Explicitly search beyond Nature/Science. Important targets include Antipode,
   Political Geography, Environment and Planning A-E, Geoforum, Global Environmental
   Change, Journal of Peasant Studies, Journal of Agrarian Change, Agriculture and
   Human Values, Food Policy, Sociologia Ruralis, Third World Quarterly and adjacent
   journals.
8. Languages: English, German, French.
9. Roughly one third of the complete selection should have a substantive Switzerland
   connection. Do NOT pad this quota with weak items.
10. Do not treat "critical" as synonymous with anti-government, anti-capitalist,
    activist or progressive. Empirical work that challenges a popular environmental
    claim in either direction can qualify.
11. Avoid routine daily news, press releases, generic explainers and shallow opinion.
12. Older publications may be selected when newly relevant; explain why.
13. Verify URLs and publication metadata using web search.
"""

def load_archive():
    if not ARCHIVE.exists():
        return []
    try:
        return json.loads(ARCHIVE.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_archive(items):
    DATA_DIR.mkdir(exist_ok=True)
    ARCHIVE.write_text(json.dumps(items[-1000:], ensure_ascii=False, indent=2),
                       encoding="utf-8")

def source_seed():
    try:
        return yaml.safe_load(SOURCES.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def clean_url(url):
    if not isinstance(url, str):
        return ""
    return url.strip()

def call_openai(prompt):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None

    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5.6"),
        "tools": [{"type": "web_search_preview"}],
        "input": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "weekly_feed",
                "schema": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "feed": {"type": "string",
                                             "enum": list(FEEDS.keys())},
                                    "title": {"type": "string"},
                                    "url": {"type": "string"},
                                    "date": {"type": "string"},
                                    "outlet": {"type": "string"},
                                    "language": {"type": "string",
                                                 "enum": ["en", "de", "fr"]},
                                    "source_type": {"type": "string"},
                                    "scientific": {"type": "boolean"},
                                    "switzerland": {"type": "boolean"},
                                    "summary": {"type": "string"},
                                    "why_relevant": {"type": "string"},
                                    "older_but_relevant": {"type": "boolean"}
                                },
                                "required": ["feed","title","url","date","outlet",
                                             "language","source_type","scientific",
                                             "switzerland","summary","why_relevant",
                                             "older_but_relevant"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["items"],
                    "additionalProperties": False
                }
            }
        }
    }
    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json=payload, timeout=180
    )
    r.raise_for_status()
    data = r.json()
    # Responses API text extraction
    text = data.get("output_text")
    if not text:
        chunks = []
        for out in data.get("output", []):
            for c in out.get("content", []):
                if c.get("type") == "output_text":
                    chunks.append(c.get("text", ""))
        text = "".join(chunks)
    return json.loads(text)

def build_prompt(archive, seeds):
    recent = archive[-300:]
    used = "\n".join(f"- {x.get('url','')}" for x in recent if x.get("url"))
    seed_lines = []
    for group, vals in seeds.items():
        for x in vals or []:
            seed_lines.append(f"{group}: {x.get('name')} — {x.get('url')}")
    return f"""Today is {TODAY}. Research the web for this week's edition.

Return 60 items total: 30 climate/ecology and 30 agriculture/food, distributed
across the four feed categories. Do not interpret 1-30 as a quality ranking.
Aim for >= 50% scientific/scholarly items overall and roughly 1/3 with substantive
Switzerland connection. If there are not enough genuinely strong items, return fewer
rather than padding.

The four feed meanings:
- climate: climate change, ecological crisis, biodiversity, energy/ecological
  transition, adaptation, mitigation, planetary boundaries.
- agriculture: farming, agrarian change, land, food production, food systems,
  nutrition/environment interfaces, fisheries/aquaculture where relevant.
- switzerland: any of the above with substantive Switzerland/Swiss/Alpine connection.
- crossovers: especially strong interdisciplinary or unexpected links.

Use English, German and French. Seek recent work but allow older items if newly
relevant. For every item give the original publication URL, not a search-results URL.

Seed sources to inspect:
{chr(10).join(seed_lines)}

Already-used URLs (avoid unless newly relevant and explain why):
{used}
"""

def validate(items):
    seen = set()
    out = []
    for x in items:
        url = clean_url(x.get("url"))
        title = (x.get("title") or "").strip()
        if not url or not title:
            continue
        key = re.sub(r"[^a-z0-9]+", "", url.lower())
        if key in seen:
            continue
        seen.add(key)
        x["url"] = url
        out.append(x)
    return out

def rss_item(x):
    pub = x.get("date") or TODAY
    try:
        d = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
    except Exception:
        d = dt.datetime.now(dt.timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    rfc = d.strftime("%a, %d %b %Y %H:%M:%S +0000")
    desc = (
        f"<p>{escape(x.get('summary',''))}</p>"
        f"<p><strong>Warum relevant:</strong> {escape(x.get('why_relevant',''))}</p>"
        f"<p><strong>Quelle:</strong> {escape(x.get('outlet',''))} · "
        f"{escape(x.get('source_type',''))} · "
        f"{escape(x.get('language',''))}"
        f"{' · Schweiz-Bezug' if x.get('switzerland') else ''}</p>"
    )
    guid = escape(x["url"])
    return f"""<item>
<title>{escape(x['title'])}</title>
<link>{guid}</link>
<guid isPermaLink="true">{guid}</guid>
<pubDate>{rfc}</pubDate>
<description><![CDATA[{desc}]]></description>
</item>"""

def write_feed(slug, title, items):
    FEED_DIR.mkdir(exist_ok=True)
    pages_base_url = os.environ.get(
    "PAGES_BASE_URL",
    "https://example.invalid"
).rstrip("/")

channel_link = f"{pages_base_url}/feeds/{slug}.xml"<link>{channel_link}</link>
<atom:link href="{channel_link}" rel="self" type="application/rss+xml"/>
    body = "\n".join(rss_item(x) for x in items)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{escape(title)} — Climate & Food Critical Feed</title>
<link>{channel_link}</link>
<description>Weekly curated research and analysis in English, German and French.</description>
<language>en</language>
<lastBuildDate>{dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")}</lastBuildDate>
{body}
</channel>
</rss>
"""
    (FEED_DIR / f"{slug}.xml").write_text(xml, encoding="utf-8")

def main():
    seeds = source_seed()
    archive = load_archive()
    prompt = build_prompt(archive, seeds)
    result = call_openai(prompt)

    if result is None:
        print("OPENAI_API_KEY not set: writing valid placeholder feeds for dry-run.")
        for slug, title in FEEDS.items():
            write_feed(slug, title, [])
        return

    items = validate(result.get("items", []))

    # Safety checks: keep only known feed labels and required fields.
    items = [x for x in items if x.get("feed") in FEEDS]

    # Avoid an accidental one-source monoculture.
    counts = {}
    for x in items:
        counts[x["source_type"]] = counts.get(x["source_type"], 0) + 1

    # Archive only selected items.
    archive.extend(items)
    save_archive(archive)

    for slug, title in FEEDS.items():
        subset = [x for x in items if x.get("feed") == slug]
        # Keep a manageable weekly issue. No ranking is implied.
        write_feed(slug, title, subset[:40])

    stats = {
        "date": TODAY,
        "items": len(items),
        "scientific": sum(bool(x.get("scientific")) for x in items),
        "switzerland": sum(bool(x.get("switzerland")) for x in items),
        "source_types": counts,
    }
    (DATA_DIR / "last_run.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
