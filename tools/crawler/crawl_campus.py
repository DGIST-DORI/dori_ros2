#!/usr/bin/env python3
"""
DORI Campus Guide Robot — Campus Knowledge Crawler
Crawls DGIST pages, extracts clean text, and refines with Google API into
structured JSON + txt documents for the RAG knowledge base.

Usage:
  # Crawl all URLs and refine with LLM
  python3 crawl_campus.py --output ./campus_documents/

  # Crawl only (no LLM, save raw text for manual review)
  python3 crawl_campus.py --output ./campus_documents/ --no-llm

  # Add more URLs at runtime
  python3 crawl_campus.py --urls extra_urls.txt --output ./campus_documents/

Dependencies:
  pip install requests beautifulsoup4 google-genai
"""

import argparse
import json
import time
import re
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# URL registry
# Format: (url, category, doc_id, description_ko, description_en)
URL_REGISTRY = [
    # 소개
    ("https://www.dgist.ac.kr/kor/sub01_02_04.do", "intro",    "dgist_history",     "학교 연혁",   "DGIST History"),
    ("https://www.dgist.ac.kr/kor/sub01_03_01.do", "intro",    "dgist_directions",  "찾아오시는 길","Directions to DGIST"),
    # 학부시설 안내
    ("https://www.dgist.ac.kr/college/sub04_01_01.do", "facility", "facility_edu",      "교육시설",    "Educational Facilities"),
    ("https://www.dgist.ac.kr/college/sub04_01_02.do", "facility", "facility_research",  "연구시설",    "Research Facilities"),
    ("https://www.dgist.ac.kr/college/sub04_01_03.do", "facility", "facility_welfare",   "복지시설",    "Welfare Facilities"),
]

# Crawl config
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DORI-CampusBot/1.0; "
        "+https://www.dgist.ac.kr)"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
REQUEST_DELAY = 1.5   # seconds between requests (be polite)
REQUEST_TIMEOUT = 15

# Tags whose content we always discard
STRIP_TAGS = [
    "script", "style", "noscript", "iframe", "header", "footer",
    "nav", "aside", "form", "button", "meta", "link",
]

# CSS selectors for common DGIST page content containers (try in order)
CONTENT_SELECTORS = [
    "#contents",
    "#content",
    ".contents_area",
    ".content_area",
    "main",
    "article",
    ".board_view",
    ".sub_content",
]


# Crawler

def fetch_page(url: str) -> str | None:
    """Fetch a URL and return raw HTML, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except Exception as e:
        print(f"  [WARN] Failed to fetch {url}: {e}")
        return None


def extract_text(html: str, url: str) -> str:
    """Extract clean readable text from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise tags
    for tag in soup(STRIP_TAGS):
        tag.decompose()

    # Try content containers first
    content = None
    for sel in CONTENT_SELECTORS:
        content = soup.select_one(sel)
        if content:
            break

    target = content if content else soup.body or soup

    # Get text, collapse whitespace
    lines = []
    for elem in target.stripped_strings:
        text = elem.strip()
        if text and len(text) > 1:
            lines.append(text)

    raw = "\n".join(lines)
    # Collapse 3+ blank lines to 2
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def crawl_url(url: str, doc_id: str) -> dict | None:
    """Crawl one URL and return a raw result dict."""
    print(f"  Fetching: {url}")
    html = fetch_page(url)
    if not html:
        return None

    text = extract_text(html, url)
    if not text:
        print(f"  [WARN] No text extracted from {url}")
        return None

    return {
        "url":        url,
        "doc_id":     doc_id,
        "raw_text":   text,
        "fetched_at": datetime.now().isoformat(),
    }


# LLM refinement

REFINE_SYSTEM = """You are a data extraction assistant for a campus guide robot at DGIST (Daegu Gyeongbuk Institute of Science and Technology), South Korea.

Your job: given raw crawled text from a DGIST webpage, extract the key information and return ONLY a valid JSON object — no markdown fences, no preamble.

JSON schema:
{
  "title_ko": "페이지 제목 (Korean)",
  "title_en": "Page title (English)",
  "summary_ko": "2-3 sentence Korean summary a robot would say to a student",
  "summary_en": "2-3 sentence English summary a robot would say to a student",
  "key_facts": [
    {"label_ko": "...", "label_en": "...", "value": "..."}
  ],
  "full_text_ko": "Clean, well-structured Korean prose preserving all important details",
  "full_text_en": "Clean, well-structured English prose preserving all important details"
}

Rules:
- Remove navigation menus, copyright notices, repeated headers, and UI chrome.
- Preserve dates, building names, room numbers, contact info, and any factual data.
- key_facts should capture the most robot-useful structured info (e.g. addresses, phone numbers, hours, names of facilities).
- If English content is absent, translate naturally from Korean.
- Return ONLY the JSON object."""


def refine_with_llm(raw_text: str, description_ko: str, description_en: str,
                    url: str) -> dict | None:
    """Call Gemini AI to refine raw crawled text into structured data."""
    try:
        from google import genai
    except ImportError:
        print("  [WARN] google-geni package not installed — skipping LLM refinement.")
        return None

    try:
        client = genai.Client()

        user_prompt = (
            f"Page: {description_ko} / {description_en}\n"
            f"URL: {url}\n\n"
            f"--- RAW TEXT ---\n{raw_text[:6000]}\n--- END ---\n\n"
            "Extract and structure the information as described."
        )

        prompt = f"{REFINE_SYSTEM}\n\n{user_prompt}"

        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        content = resp.text.strip()

        # Strip accidental markdown fences
        content = re.sub(r"^```json\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        return json.loads(content)
    
    except json.JSONDecodeError as e:
        print(f"  [WARN] LLM returned invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"  [WARN] LLM API error: {e}")
        return None


# Output writers

def save_raw(raw: dict, out_dir: Path):
    """Save raw crawled text for review or re-processing."""
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{raw['doc_id']}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"URL: {raw['url']}\n")
        f.write(f"Fetched: {raw['fetched_at']}\n")
        f.write("=" * 60 + "\n\n")
        f.write(raw["raw_text"])
    print(f"  [RAW]  -> {path}")


def save_refined(refined: dict, raw: dict, category: str,
                 description_ko: str, description_en: str, out_dir: Path):
    """Save LLM-refined data as JSON + txt."""
    doc_id = raw["doc_id"]

    # JSON (structured metadata + key facts)
    json_payload = {
        "doc_id":        doc_id,
        "category":      category,
        "url":           raw["url"],
        "fetched_at":    raw["fetched_at"],
        "description_ko": description_ko,
        "description_en": description_en,
        "title_ko":      refined.get("title_ko", ""),
        "title_en":      refined.get("title_en", ""),
        "summary_ko":    refined.get("summary_ko", ""),
        "summary_en":    refined.get("summary_en", ""),
        "key_facts":     refined.get("key_facts", []),
    }

    json_dir = out_dir / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_dir / f"{doc_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, ensure_ascii=False, indent=2)
    print(f"  [JSON] -> {json_path}")

    # TXT (full prose, for RAG vector search)
    txt_dir = out_dir / category
    txt_dir.mkdir(parents=True, exist_ok=True)
    txt_path = txt_dir / f"{doc_id}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"[{refined.get('title_ko', description_ko)}]\n")
        f.write(f"출처: {raw['url']}\n\n")
        f.write(refined.get("full_text_ko", "") + "\n\n")
        f.write("---\n\n")
        f.write(f"[{refined.get('title_en', description_en)}]\n")
        f.write(f"Source: {raw['url']}\n\n")
        f.write(refined.get("full_text_en", "") + "\n")
    print(f"  [TXT]  -> {txt_path}")


def save_fallback_txt(raw: dict, category: str,
                      description_ko: str, description_en: str, out_dir: Path):
    """Save raw text as txt when LLM refinement fails/skipped."""
    txt_dir = out_dir / category
    txt_dir.mkdir(parents=True, exist_ok=True)
    txt_path = txt_dir / f"{raw['doc_id']}_raw.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"[{description_ko} / {description_en}]\n")
        f.write(f"URL: {raw['url']}\n\n")
        f.write(raw["raw_text"])
    print(f"  [TXT]  -> {txt_path} (raw fallback)")


# URL list loader

def load_extra_urls(path: str) -> list[tuple]:
    """
    Load extra URLs from a text file.
    Format (one per line):
      https://... [category] [doc_id] # optional comment
    or plain URL lines (category=misc, doc_id auto-generated).
    """
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            url = parts[0]
            category = parts[1] if len(parts) > 1 else "misc"
            doc_id   = parts[2] if len(parts) > 2 else (
                urlparse(url).path.strip("/").replace("/", "_") or "page"
            )
            entries.append((url, category, doc_id, doc_id, doc_id))
    return entries


# Main

def main():
    parser = argparse.ArgumentParser(description="DORI Campus Knowledge Crawler")
    parser.add_argument("--output", default="./campus_documents",
                        help="Output root directory")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM refinement, save raw text only")
    parser.add_argument("--urls", default=None,
                        help="Path to extra URL list file")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY,
                        help=f"Delay between requests in seconds (default {REQUEST_DELAY})")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    registry = list(URL_REGISTRY)
    if args.urls:
        registry += load_extra_urls(args.urls)

    print(f"DORI Crawler — {len(registry)} URL(s) to process\n")

    for url, category, doc_id, desc_ko, desc_en in registry:
        print(f"[{doc_id}] {desc_ko}")

        raw = crawl_url(url, doc_id)
        if not raw:
            print("  [SKIP] Could not fetch page.\n")
            continue

        save_raw(raw, out_dir)

        if not args.no_llm:
            print("  Refining with LLM...")
            refined = refine_with_llm(raw["raw_text"], desc_ko, desc_en, url)
            if refined:
                save_refined(refined, raw, category, desc_ko, desc_en, out_dir)
            else:
                print("  [WARN] LLM refinement failed — saving raw fallback.")
                save_fallback_txt(raw, category, desc_ko, desc_en, out_dir)
        else:
            save_fallback_txt(raw, category, desc_ko, desc_en, out_dir)

        time.sleep(args.delay)

    print(f"\nDone. Output -> {out_dir}")


if __name__ == "__main__":
    main()
