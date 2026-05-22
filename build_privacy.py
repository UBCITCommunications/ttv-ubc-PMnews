#!/usr/bin/env python3
"""
Fetches UBC Privacy Matters announcements RSS feed, extracts the first image
and a clean summary from each item's description HTML, writes privacy.json.

Unlike the IT news feed (which wraps the hero image in a specific Drupal div),
this feed's images are plain <img> tags inside the body. We grab the first one
as the hero.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests


FEED_URL     = "https://privacymatters.ubc.ca/announcements/rss.xml"
MAX_ITEMS    = 8
MAX_AGE_DAYS = 180   # PM posts less often than IT — wider window
SUMMARY_LEN  = 350

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36 UBC-Signage-Bot/1.0",
    "Accept": "application/rss+xml, application/xml, text/xml",
}


def extract_first_image(html):
    """First <img> in the description — that's the hero on privacymatters."""
    m = re.search(r'<img[^>]+src="(https?://[^"]+)"', html)
    return m.group(1) if m else None


def extract_tag(html):
    """Grab the <li class="tag">...</li> value if present (Article, News, Security Bulletin)."""
    m = re.search(r'<li class="tag">([^<]+)</li>', html)
    return m.group(1).strip() if m else None


def strip_html(html):
    """Strip HTML tags + decode common entities + collapse whitespace."""
    if not html:
        return ""

    # Drop the title duplicate that Drupal includes at the start
    html = re.sub(
        r'<span class="field field--name-title[^"]*"[^>]*>.*?</span>',
        '', html, flags=re.DOTALL
    )
    # Drop UID and created-date metadata blocks
    html = re.sub(
        r'<span class="field field--name-uid[^"]*"[^>]*>.*?</span>',
        '', html, flags=re.DOTALL
    )
    html = re.sub(
        r'<span class="field field--name-created[^"]*"[^>]*>.*?</span>',
        '', html, flags=re.DOTALL
    )
    # Drop node__links footer
    html = re.sub(
        r'<div class="node__links">.*?</div>',
        '', html, flags=re.DOTALL
    )
    # Drop the tag list (we extract it separately)
    html = re.sub(
        r'<ul class="inline-flex[^"]*">.*?</ul>',
        '', html, flags=re.DOTALL
    )

    # Remove iframes/scripts/style blocks
    html = re.sub(r'<(iframe|script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', ' ', html)

    # Decode entities we care about
    replacements = {
        '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>',
        '&#8217;': '\u2019', '&#8220;': '\u201c', '&#8221;': '\u201d',
        '&#8211;': '\u2013', '&#8212;': '\u2014', '&quot;': '"', '&apos;': "'",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Numeric entities
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)

    # Collapse whitespace
    return re.sub(r'\s+', ' ', text).strip()


def truncate_at_word(s, max_len):
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    last_space = cut.rfind(' ')
    return cut[:last_space if last_space > 0 else max_len].rstrip() + '\u2026'


def extract_guid_id(guid):
    """Pull the numeric node ID from a guid like '907 at https://privacymatters.ubc.ca'."""
    if not guid:
        return None
    m = re.match(r'(\d+)', guid.strip())
    return m.group(1) if m else None


def main():
    print(f"Fetching {FEED_URL}")
    r = requests.get(FEED_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    # Parse RSS XML
    root = ET.fromstring(r.content)
    channel = root.find('channel')
    if channel is None:
        print("ERROR: no <channel> in feed", file=sys.stderr)
        sys.exit(1)

    items_raw = channel.findall('item')
    print(f"Feed has {len(items_raw)} items")

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=MAX_AGE_DAYS)

    items = []
    for it in items_raw:
        title       = (it.findtext('title')       or '').strip()
        link        = (it.findtext('link')        or '').strip()
        description = (it.findtext('description') or '')
        pub_raw     = (it.findtext('pubDate')     or '').strip()
        guid_raw    = (it.findtext('guid')        or '').strip()

        # Parse pubDate
        try:
            pub_dt = parsedate_to_datetime(pub_raw)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            print(f"  skipping (bad pubDate): {title!r}")
            continue

        # Age filter
        if pub_dt < cutoff:
            print(f"  skipping (older than {MAX_AGE_DAYS}d): {title!r}")
            continue

        image = extract_first_image(description)
        if not image:
            print(f"  skipping (no image): {title!r}")
            continue

        summary = truncate_at_word(strip_html(description), SUMMARY_LEN)
        tag     = extract_tag(description)
        node_id = extract_guid_id(guid_raw)

        items.append({
            "id":      node_id,
            "title":   title,
            "link":    link,
            "image":   image,
            "pub_iso": pub_dt.isoformat(),
            "summary": summary,
            "tag":     tag,
        })

        if len(items) >= MAX_ITEMS:
            break

    out = {
        "generated_at": now_utc.isoformat(),
        "count":        len(items),
        "items":        items,
    }

    with open('privacy.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(items)} items to privacy.json")


if __name__ == '__main__':
    main()
