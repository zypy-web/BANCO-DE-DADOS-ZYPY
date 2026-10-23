#!/usr/bin/env python3
"""Append real, direct KaBuM product URLs discovered through sitemaps and public listings."""
from __future__ import annotations

import base64
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

OWNER = "zypy-web"
REPO = "BANCO-DE-DADOS-ZYPY"
FILE_PATH = "LINKS"
GITHUB_CONTENTS = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{FILE_PATH}"
MIN_TOTAL = 501
TARGET_NEW = 500
MAX_TOTAL_SITEMAPS = 160
MAX_LISTING_REQUESTS = 180
TIMEOUT = 20

SITEMAP_SEEDS = [
    "https://www.kabum.com.br/robots.txt",
    "https://www.kabum.com.br/sitemap.xml",
    "https://www.kabum.com.br/sitemap_index.xml",
]
CATEGORY_SEEDS = [
    "https://www.kabum.com.br/",
    "https://www.kabum.com.br/hardware",
    "https://www.kabum.com.br/hardware/placa-de-video",
    "https://www.kabum.com.br/hardware/processadores",
    "https://www.kabum.com.br/hardware/placa-mae",
    "https://www.kabum.com.br/hardware/memoria-ram",
    "https://www.kabum.com.br/hardware/ssd",
    "https://www.kabum.com.br/hardware/fontes",
    "https://www.kabum.com.br/hardware/gabinetes",
    "https://www.kabum.com.br/hardware/coolers",
    "https://www.kabum.com.br/hardware/water-cooler",
    "https://www.kabum.com.br/computadores",
    "https://www.kabum.com.br/computadores/pc-gamer",
    "https://www.kabum.com.br/computadores/notebook",
    "https://www.kabum.com.br/perifericos",
    "https://www.kabum.com.br/perifericos/mouse",
    "https://www.kabum.com.br/perifericos/teclado",
    "https://www.kabum.com.br/perifericos/headset",
    "https://www.kabum.com.br/perifericos/microfone",
    "https://www.kabum.com.br/monitores",
    "https://www.kabum.com.br/espaco-gamer/cadeiras-gamer",
    "https://www.kabum.com.br/games",
    "https://www.kabum.com.br/games/gift-card",
    "https://www.kabum.com.br/gift-card",
    "https://www.kabum.com.br/consoles",
    "https://www.kabum.com.br/audio",
]
SEARCH_TERMS = [
    "placa-de-video", "rtx-5060", "rtx-5070", "rtx-5080", "radeon-rx",
    "processador-amd-ryzen", "processador-intel-core", "placa-mae",
    "memoria-ram-ddr4", "memoria-ram-ddr5", "ssd-nvme", "ssd-1tb",
    "fonte-750w", "gabinete-gamer", "water-cooler", "monitor-gamer",
    "mouse-gamer", "teclado-mecanico", "headset-gamer", "microfone-usb",
    "cadeira-gamer", "notebook-gamer", "pc-gamer", "controle-ps5",
    "controle-xbox", "playstation-5", "xbox-series", "nintendo-switch",
    "gift-card-xbox", "gift-card-playstation", "gift-card-nintendo",
    "gift-card-roblox", "gift-card-google-play", "jogo-ps5",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}

def fetch(url: str) -> tuple[str, str] | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            data = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            if url.lower().endswith(".gz") or response.headers.get("Content-Encoding") == "gzip":
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            return data.decode(charset, errors="replace"), response.geturl()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"FETCH_FAIL {url}: {exc}", file=sys.stderr)
        return None

def normalize_product(raw: str) -> str | None:
    raw = html.unescape(raw.strip()).replace("\\/", "/").replace("\\u002F", "/")
    if raw.startswith("//"):
        raw = "https:" + raw
    if raw.startswith("/produto/"):
        raw = "https://www.kabum.com.br" + raw
    elif raw.startswith("www.kabum.com.br/"):
        raw = "https://" + raw
    try:
        p = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    if host not in {"kabum.com.br", "www.kabum.com.br"}:
        return None
    match = re.match(r"^/produto/(\d+)(?:/([^?#\"'<>\s]+))?", p.path, flags=re.I)
    if not match:
        return None
    pid, slug = match.group(1), match.group(2)
    path = f"/produto/{pid}" + (f"/{slug.rstrip('/')}" if slug else "")
    return "https://www.kabum.com.br" + path

PRODUCT_PATTERN = re.compile(
    r"""(?:(?:https?:)?//(?:www\.)?kabum\.com\.br)?(/produto/\d+(?:/[^"'<>\\\s?#]*)?)""",
    re.IGNORECASE,
)

def product_urls_from_text(text: str) -> list[str]:
    # Product links also appear JSON-escaped in server-rendered script payloads.
    prepared = html.unescape(text).replace("\\/", "/").replace("\\u002F", "/")
    found = []
    for match in PRODUCT_PATTERN.finditer(prepared):
        url = normalize_product(match.group(0))
        if url:
            found.append(url)
    return found

def normal_key(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return f"https://www.kabum.com.br{p.path.rstrip('/')}".lower()

def add_from_text(text: str, discovered: dict[str, str], existing: set[str]) -> int:
    before = len(discovered)
    for url in product_urls_from_text(text):
        key = normal_key(url)
        if key not in existing and key not in discovered:
            discovered[key] = url
            if len(discovered) >= TARGET_NEW:
                break
    return len(discovered) - before

def extract_locs(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
        return [
            node.text.strip()
            for node in root.iter()
            if node.tag.rsplit("}", 1)[-1].lower() == "loc" and node.text and node.text.strip()
        ]
    except ET.ParseError:
        return [html.unescape(x.strip()) for x in re.findall(r"<loc[^>]*>(.*?)</loc>", xml_text, re.I | re.S)]

def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Missing GITHUB_TOKEN.", file=sys.stderr)
        return 1
    gh_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ZYPY-KaBuM-Link-Collector/2.0",
    }
    req = urllib.request.Request(GITHUB_CONTENTS, headers=gh_headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            current = json.loads(response.read().decode("utf-8"))
        existing_text = base64.b64decode(current["content"]).decode("utf-8")
    except Exception as exc:
        print(f"Could not safely read current LINKS file: {exc}", file=sys.stderr)
        return 1

    existing_lines = [line.strip() for line in existing_text.splitlines() if line.strip()]
    existing_keys = {normal_key(line) for line in existing_lines}
    discovered: dict[str, str] = {}

    # First pass: robots.txt and XML sitemap indexes/sitemaps.
    queue = list(SITEMAP_SEEDS)
    seen_sitemaps: set[str] = set()
    while queue and len(seen_sitemaps) < MAX_TOTAL_SITEMAPS and len(discovered) < TARGET_NEW:
        sm_url = queue.pop(0)
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)
        result = fetch(sm_url)
        if not result:
            continue
        body, final_url = result
        if sm_url.endswith("robots.txt") or final_url.endswith("robots.txt"):
            for candidate in re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", body):
                if candidate not in seen_sitemaps and candidate not in queue:
                    queue.append(candidate)
            # robots can also include product URL paths in some implementations.
            add_from_text(body, discovered, existing_keys)
            continue
        if "<loc" in body.lower() or "<sitemapindex" in body.lower() or "<urlset" in body.lower():
            locs = extract_locs(body)
            queue_count = 0
            for loc in locs:
                url = normalize_product(loc)
                if url:
                    key = normal_key(url)
                    if key not in existing_keys and key not in discovered:
                        discovered[key] = url
                elif loc.lower().endswith((".xml", ".xml.gz")) or "sitemap" in loc.lower():
                    if loc not in seen_sitemaps and loc not in queue:
                        queue.append(loc)
                        queue_count += 1
            print(f"SITEMAP {sm_url}: {len(locs)} locations, {len(discovered)} new products, {queue_count} child sitemaps")
        else:
            add_from_text(body, discovered, existing_keys)
        if len(discovered) >= TARGET_NEW:
            break
        time.sleep(0.08)

    # Second pass: public category/search listings rendered by KaBuM, useful if sitemap is unavailable.
    fetch_count = 0
    listing_queue: list[str] = list(CATEGORY_SEEDS)
    for term in SEARCH_TERMS:
        listing_queue.append("https://www.kabum.com.br/busca/" + urllib.parse.quote(term, safe="-"))
    visited: set[str] = set()
    while listing_queue and fetch_count < MAX_LISTING_REQUESTS and len(discovered) < TARGET_NEW:
        page_url = listing_queue.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)
        fetch_count += 1
        result = fetch(page_url)
        if not result:
            continue
        body, final_url = result
        added = add_from_text(body, discovered, existing_keys)

        # Follow pagination/category links found directly in page markup, restricting to same storefront.
        if fetch_count <= 45 and len(discovered) < TARGET_NEW:
            prepared = html.unescape(body).replace("\\/", "/").replace("\\u002F", "/")
            for href in re.findall(r"""href\s*=\s*["']([^"']+)["']""", prepared, re.I):
                href = href.strip()
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.kabum.com.br" + href
                elif href.startswith("www.kabum.com.br/"):
                    href = "https://" + href
                parsed = urllib.parse.urlsplit(href)
                host = (parsed.hostname or "").lower()
                if host not in {"kabum.com.br", "www.kabum.com.br"}:
                    continue
                path = parsed.path.lower()
                if re.search(r"/produto/\d+", path):
                    continue
                if any(word in path for word in (
                    "/hardware", "/perifer", "/computadores", "/monitor", "/espaco-gamer",
                    "/games", "/gift-card", "/console", "/busca", "/audio", "/celular"
                )):
                    normalized = urllib.parse.urlunsplit(("https", "www.kabum.com.br", parsed.path, parsed.query, ""))
                    if normalized not in visited and normalized not in listing_queue:
                        listing_queue.append(normalized)
            # Probe common pagination variants for a small set of high-volume categories.
            if fetch_count <= len(CATEGORY_SEEDS) and len(discovered) < TARGET_NEW:
                for param in ("page_number", "page", "pagina"):
                    for pg in (2, 3):
                        parsed = urllib.parse.urlsplit(final_url)
                        q = urllib.parse.parse_qs(parsed.query)
                        q[param] = [str(pg)]
                        query = urllib.parse.urlencode(q, doseq=True)
                        candidate = urllib.parse.urlunsplit((parsed.scheme or "https", parsed.netloc or "www.kabum.com.br", parsed.path, query, ""))
                        if candidate not in visited and candidate not in listing_queue:
                            listing_queue.append(candidate)
        print(f"LISTING {fetch_count}/{MAX_LISTING_REQUESTS}: {page_url} -> +{added}, total new {len(discovered)}")
        time.sleep(0.06)

    final_lines = existing_lines + list(discovered.values())
    final_keys = {normal_key(line) for line in final_lines}
    print(f"RESULT existing={len(existing_lines)} unique_existing={len(existing_keys)} new={len(discovered)} total_unique={len(final_keys)}")
    if len(final_keys) < MIN_TOTAL:
        print(
            f"Safety stop: only {len(final_keys)} unique direct product URLs found; "
            f"need at least {MIN_TOTAL}. LINKS was not changed.",
            file=sys.stderr,
        )
        return 1

    updated_text = "\n".join(final_lines) + "\n"
    body = {
        "message": f"Add {len(discovered)} direct KaBuM product links ({len(final_keys)} unique total)",
        "content": base64.b64encode(updated_text.encode("utf-8")).decode("ascii"),
        "sha": current["sha"],
        "branch": "main",
    }
    put_req = urllib.request.Request(
        GITHUB_CONTENTS,
        data=json.dumps(body).encode("utf-8"),
        headers={**gh_headers, "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(put_req, timeout=TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"GitHub update failed: {exc}", file=sys.stderr)
        return 1
    print(f"SUCCESS: LINKS now has {len(final_keys)} unique direct KaBuM product URLs; added {len(discovered)}.")
    print(result.get("commit", {}).get("html_url", "Commit created."))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
