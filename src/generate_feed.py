#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import yaml
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
FEEDS_DIR = ROOT / "feeds"
DATA_DIR = ROOT / "data"
ARCHIVE_FILE = DATA_DIR / "archive.json"
SOURCES_FILE = ROOT / "src" / "sources.yml"

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6")
EXPECTED_TOTAL = 60


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_sources():
    with SOURCES_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_json(text):
    text = text.strip()
    for candidate in (
        text,
        re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip(),
    ):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    for start, ch in enumerate(text):
        if ch not in "[{":
            continue
        opener, closer = ch, ("]" if ch == "[" else "}")
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            c = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
    raise ValueError("Could not extract valid JSON from model response.")


def normalize_items(payload):
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("JSON must contain an 'items' list.")
    return items


def valid_url(url):
    if not isinstance(url, str):
        return False
    p = urlparse(url.strip())
    return p.scheme in {"http", "https"} and bool(p.netloc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def clean_item(raw):
    required = [
        "feed", "title", "url", "date", "outlet", "language",
        "source_type", "scientific", "switzerland", "summary", "why_relevant"
    ]
    if not isinstance(raw, dict) or any(k not in raw for k in required):
        return None

    feed = str(raw["feed"]).strip().lower()
    if feed not in {"climate", "agriculture"}:
        return None

    title = str(raw["title"]).strip()
    url = str(raw["url"]).strip()
    outlet = str(raw["outlet"]).strip()
    language = str(raw["language"]).strip().lower()
    summary = str(raw["summary"]).strip()
    why = str(raw["why_relevant"]).strip()
    date = parse_date(raw["date"])

    if not title or not valid_url(url) or not outlet or not summary or not why or date is None:
        return None
    if language not in {"en", "de", "fr"}:
        return None

    return {
        "feed": feed,
        "title": title,
        "url": url,
        "date": date.isoformat(),
        "outlet": outlet,
        "language": language,
        "source_type": str(raw["source_type"]).strip(),
        "scientific": bool(raw["scientific"]),
        "switzerland": bool(raw["switzerland"]),
        "summary": summary,
        "why_relevant": why,
        "older_but_relevant": bool(raw.get("older_but_relevant", False)),
    }


def validate_and_dedupe(items):
    result, seen = [], set()
    for raw in items:
        item = clean_item(raw)
        if item is None:
            continue
        key = item["url"].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def validate_collection(items):
    if len(items) != EXPECTED_TOTAL:
        fail(f"Expected exactly 60 valid items, got {len(items)}.")

    climate = sum(x["feed"] == "climate" for x in items)
    agriculture = sum(x["feed"] == "agriculture" for x in items)
    scientific = sum(x["scientific"] for x in items)
    swiss = sum(x["switzerland"] for x in items)

    if climate != 30:
        fail(f"Expected 30 climate items, got {climate}.")
    if agriculture != 30:
        fail(f"Expected 30 agriculture items, got {agriculture}.")
    if scientific < 30:
        fail(f"Scientific share too low: {scientific}/60.")
    if swiss < 18:
        fail(f"Switzerland share too low: {swiss}/60.")

    return climate, agriculture, scientific, swiss


def build_prompt(sources):
    source_text = yaml.safe_dump(sources, allow_unicode=True, sort_keys=False)
    return f"""
You are the weekly research curator for a high-quality RSS research feed.

Return EXACTLY 60 distinct items as JSON:
{{
  "items": [
    {{
      "feed": "climate|agriculture",
      "title": "...",
      "url": "https://...",
      "date": "YYYY-MM-DD",
      "outlet": "...",
      "language": "en|de|fr",
      "source_type": "journal|preprint|report|investigation|analysis|other",
      "scientific": true,
      "switzerland": false,
      "summary": "2-3 factual sentences",
      "why_relevant": "1-2 sentences explaining the surprising/critical relevance",
      "older_but_relevant": false
    }}
  ]
}}

STRICT DISTRIBUTION:
- exactly 30 climate items
- exactly 30 agriculture/food items
- at least 30/60 genuinely scientific/scholarly
- at least 18/60 substantively Switzerland-related
- Include English, German and French material where useful.
- About half or more should be science, including critical social sciences:
  human geography, political ecology, agrarian studies, rural sociology,
  social anthropology, environmental history and political economy.
- Explicitly search beyond Nature/Science, including Political Geography,
  Antipode, Environment and Planning A/E, Geoforum, Global Environmental Change,
  Journal of Peasant Studies, Journal of Agrarian Change, Agriculture and Human
  Values, Food Policy, Sociologia Ruralis and Third World Quarterly.
- Also search specialist journalism, NGOs, intergovernmental reports and Swiss
  research institutions.
- Do not rank items and do not favor large outlets.
- Prefer original research, systematic reviews, substantial reports and
  investigative/analytical journalism over routine news.
- "Critical" does not automatically mean anti-government or anti-capitalist.
  Include evidence challenging popular assumptions in any direction.
- Older publications are allowed if newly relevant; mark them true.
- URLs must be direct URLs to the actual publication/report/article.
- Dates must be actual publication dates.
- Never invent publications, URLs, dates, titles or outlets.
- Search the web extensively before returning the JSON.
- Return JSON only.

Seed sources (not a restriction):
{source_text}
"""


def research():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        fail("OPENAI_API_KEY is not set.")

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=MODEL,
        tools=[{"type": "web_search_preview"}],
        input=build_prompt(load_sources()),
    )

    text = getattr(response, "output_text", None)
    if not text:
        fail("OpenAI response contained no output_text.")

    try:
        payload = extract_json(text)
        items = validate_and_dedupe(normalize_items(payload))
    except Exception as exc:
        print("Raw model response for debugging:")
        print(text[:12000])
        fail(f"Could not parse/validate model JSON: {exc}")

    stats = validate_collection(items)
    print(
        f"Validated 60 items: climate={stats[0]}, agriculture={stats[1]}, "
        f"scientific={stats[2]}/60, Switzerland={stats[3]}/60"
    )
    return items


def save_archive(items):
    archive = []
    if ARCHIVE_FILE.exists():
        try:
            archive = json.loads(ARCHIVE_FILE.read_text(encoding="utf-8"))
        except Exception:
            archive = []

    known = {x.get("url", "").rstrip("/").lower() for x in archive}
    for item in items:
        if item["url"].rstrip("/").lower() not in known:
            archive.append(item)

    ARCHIVE_FILE.write_text(
        json.dumps(archive, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def rss_item(item):
    pubdate = format_datetime(parse_date(item["date"]))
    description = (
        f"<p>{escape(item['summary'])}</p>"
        f"<p><strong>Why relevant:</strong> {escape(item['why_relevant'])}</p>"
        f"<p><strong>Source:</strong> {escape(item['outlet'])} "
        f"({escape(item['source_type'])}, {escape(item['language'])})</p>"
    )
    return (
        "<item>\n"
        f"<title>{escape(item['title'])}</title>\n"
        f"<link>{escape(item['url'])}</link>\n"
        f"<guid isPermaLink=\"true\">{escape(item['url'])}</guid>\n"
        f"<pubDate>{pubdate}</pubDate>\n"
        f"<description><![CDATA[{description}]]></description>\n"
        "</item>"
    )


def write_feed(slug, title, items):
    base = os.environ.get("PAGES_BASE_URL", "").rstrip("/")
    if not base:
        fail("PAGES_BASE_URL is not set.")
    if not items:
        fail(f"Refusing to write empty feed: {slug}")

    channel_link = f"{base}/feeds/{slug}.xml"
    xml_items = "\n".join(
        rss_item(x) for x in sorted(items, key=lambda x: x["date"], reverse=True)
    )
    now = format_datetime(datetime.now(timezone.utc))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        f"<title>{escape(title)}</title>\n"
        f"<link>{escape(channel_link)}</link>\n"
        f'<atom:link href="{escape(channel_link)}" rel="self" type="application/rss+xml"/>\n'
        "<description>Weekly curated research and analysis in English, German and French.</description>\n"
        "<language>en</language>\n"
        f"<lastBuildDate>{now}</lastBuildDate>\n"
        f"{xml_items}\n"
        "</channel>\n"
        "</rss>\n"
    )

    path = FEEDS_DIR / f"{slug}.xml"
    path.write_text(xml, encoding="utf-8")
    print(f"Wrote {path} ({len(items)} items)")


def main():
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    items = research()

    climate = [x for x in items if x["feed"] == "climate"]
    agriculture = [x for x in items if x["feed"] == "agriculture"]
    switzerland = [x for x in items if x["switzerland"]]

    crossovers = [
        x for x in items
        if "food" in (x["title"] + " " + x["summary"]).lower()
        and any(
            term in (x["title"] + " " + x["summary"]).lower()
            for term in [
                "climate", "carbon", "emission", "warming",
                "biodiversity", "ecology", "drought", "heat"
            ]
        )
    ]

    if len(switzerland) < 6:
        fail("Too few Switzerland-linked items for the Switzerland feed.")
    if not crossovers:
        fail("No climate/food crossover items identified.")

    write_feed("climate", "Climate & Ecology — Critical Research Feed", climate)
    write_feed("agriculture", "Agriculture & Food Systems — Critical Research Feed", agriculture)
    write_feed("switzerland", "Switzerland — Climate, Ecology, Agriculture & Food", switzerland)
    write_feed("crossovers", "Crossovers & Wild Cards — Climate, Ecology, Agriculture & Food", crossovers)

    save_archive(items)
    print("Feed generation completed successfully.")


if __name__ == "__main__":
    main()
