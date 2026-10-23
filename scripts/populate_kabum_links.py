#!/usr/bin/env python3
"""Append unique, direct KaBuM product URLs from storefront sitemaps and listing pages."""
from __future__ import annotations
import base64, gzip, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

OWNER, REPO, FILE_PATH = "zypy-web", "BANCO-DE-DADOS-ZYPY", "LINKS"
GITHUB_CONTENTS = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{FILE_PATH}"
MIN_TOTAL = 501
TARGET_NEW = 10000
MAX_TOTAL_SITEMAPS = 220
MAX_LISTING_REQUESTS = 240
TIMEOUT = 22
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
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}

def fetch(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            data = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            if url.lower().endswith(".gz") or response.headers.get("Content-Encoding") == "gzip":
                try: data = gzip.decompress(data)
                except OSError: pass
            return data.decode(charset, errors="replace"), response.geturl()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"FETCH_FAIL {url}: {exc}", file=sys.stderr)
        return None

def normalize_product(raw: str):
    raw = html.unescape(raw.strip()).replace("\\/", "/").replace("\\u002F", "/")
    if raw.startswith("//"): raw = "https:" + raw
    if raw.startswith("/produto/"): raw = "https://www.kabum.com.br" + raw
    elif raw.startswith("www.kabum.com.br/"): raw = "https://" + raw
    try: p = urllib.parse.urlsplit(raw)
    except ValueError: return None
    if (p.hostname or "").lower() not in {"kabum.com.br", "www.kabum.com.br"}: return None
    match = re.match(r"^/produto/(\d+)(?:/([^?#\"'<>\\s]+))?", p.path, re.I)
    if not match: return None
    pid, slug = match.group(1), match.group(2)
    return "https://www.kabum.com.br/produto/" + pid + (("/" + slug.rstrip("/")) if slug else "")

PRODUCT_PATTERN = re.compile(
    r"""(?:(?:https?:)?//(?:www\.)?kabum\.com\.br)?(/produto/\d+(?:/[^"'<>\\\s?#]*)?)""",
    re.I,
)
def product_urls_from_text(text: str):
    prepared = html.unescape(text).replace("\\/", "/").replace("\\u002F", "/")
    found = []
    for match in PRODUCT_PATTERN.finditer(prepared):
        url = normalize_product(match.group(0))
        if url: found.append(url)
    return found

def normal_key(url: str):
    p = urllib.parse.urlsplit(url)
    return f"https://www.kabum.com.br{p.path.rstrip('/')}".lower()

def add_from_text(text: str, discovered: dict[str,str], existing: set[str]):
    before = len(discovered)
    for url in product_urls_from_text(text):
        key = normal_key(url)
        if key not in existing and key not in discovered and len(discovered) < TARGET_NEW:
            discovered[key] = url
    return len(discovered) - before

def extract_locs(xml_text: str):
    try:
        root = ET.fromstring(xml_text)
        return [n.text.strip() for n in root.iter() if n.tag.rsplit("}",1)[-1].lower()=="loc" and n.text and n.text.strip()]
    except ET.ParseError:
        return [html.unescape(x.strip()) for x in re.findall(r"<loc[^>]*>(.*?)</loc>", xml_text, re.I|re.S)]

def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Missing GITHUB_TOKEN.", file=sys.stderr); return 1
    gh_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ZYPY-KaBuM-Link-Collector/3.0",
    }
    try:
        req = urllib.request.Request(GITHUB_CONTENTS, headers=gh_headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            current = json.loads(response.read().decode("utf-8"))
        existing_text = base64.b64decode(current["content"]).decode("utf-8")
    except Exception as exc:
        print(f"Could not safely read current LINKS: {exc}", file=sys.stderr); return 1

    existing_lines = [x.strip() for x in existing_text.splitlines() if x.strip()]
    existing_keys = {normal_key(line) for line in existing_lines if normalize_product(line)}
    discovered: dict[str,str] = {}
    queue = list(SITEMAP_SEEDS)
    seen_sitemaps: set[str] = set()

    # Traverse every discovered sitemap instead of stopping at the first sitemap with 500 products.
    while queue and len(seen_sitemaps) < MAX_TOTAL_SITEMAPS and len(discovered) < TARGET_NEW:
        sm_url = queue.pop(0)
        if sm_url in seen_sitemaps: continue
        seen_sitemaps.add(sm_url)
        result = fetch(sm_url)
        if not result: continue
        body, final_url = result
        if sm_url.endswith("robots.txt") or final_url.endswith("robots.txt"):
            for candidate in re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", body):
                if candidate not in seen_sitemaps and candidate not in queue: queue.append(candidate)
            add_from_text(body, discovered, existing_keys)
            continue
        if "<loc" in body.lower() or "<sitemapindex" in body.lower() or "<urlset" in body.lower():
            locs = extract_locs(body)
            child_added = 0
            for loc in locs:
                product = normalize_product(loc)
                if product:
                    key = normal_key(product)
                    if key not in existing_keys and key not in discovered and len(discovered) < TARGET_NEW:
                        discovered[key] = product
                elif loc.lower().endswith((".xml", ".xml.gz")) or "sitemap" in loc.lower():
                    if loc not in seen_sitemaps and loc not in queue:
                        queue.append(loc); child_added += 1
            print(f"SITEMAP {sm_url}: {len(locs)} locations, {len(discovered)} new product URLs, {child_added} child sitemaps queued")
        else:
            add_from_text(body, discovered, existing_keys)
        time.sleep(0.06)

    # Fall back to category/search pages and linked categories if sitemaps did not yield much.
    fetch_count = 0
    listing_queue = list(CATEGORY_SEEDS) + [
        "https://www.kabum.com.br/busca/" + urllib.parse.quote(term, safe="-")
        for term in SEARCH_TERMS
    ]
    visited: set[str] = set()
    while listing_queue and fetch_count < MAX_LISTING_REQUESTS and len(discovered) < TARGET_NEW:
        page_url = listing_queue.pop(0)
        if page_url in visited: continue
        visited.add(page_url); fetch_count += 1
        result = fetch(page_url)
        if not result: continue
        body, final_url = result
        added = add_from_text(body, discovered, existing_keys)
        if fetch_count <= 70 and len(discovered) < TARGET_NEW:
            prepared = html.unescape(body).replace("\\/", "/").replace("\\u002F", "/")
            for href in re.findall(r"""href\s*=\s*["']([^"']+)["']""", prepared, re.I):
                href = href.strip()
                if href.startswith("//"): href = "https:" + href
                elif href.startswith("/"): href = "https://www.kabum.com.br" + href
                elif href.startswith("www.kabum.com.br/"): href = "https://" + href
                try: parsed = urllib.parse.urlsplit(href)
                except ValueError: continue
                if (parsed.hostname or "").lower() not in {"kabum.com.br","www.kabum.com.br"}: continue
                path = parsed.path.lower()
                if re.search(r"/produto/\d+", path): continue
                if any(x in path for x in ("/hardware","/perifer","/computadores","/monitor","/espaco-gamer","/games","/gift-card","/console","/busca","/audio","/celular")):
                    normalized = urllib.parse.urlunsplit(("https","www.kabum.com.br",parsed.path,parsed.query,""))
                    if normalized not in visited and normalized not in listing_queue: listing_queue.append(normalized)
            if fetch_count <= len(CATEGORY_SEEDS):
                parsed = urllib.parse.urlsplit(final_url)
                for param in ("page_number","page","pagina"):
                    for pg in (2,3,4,5):
                        q = urllib.parse.parse_qs(parsed.query); q[param] = [str(pg)]
                        candidate = urllib.parse.urlunsplit((parsed.scheme or "https",parsed.netloc or "www.kabum.com.br",parsed.path,urllib.parse.urlencode(q,doseq=True),""))
                        if candidate not in visited and candidate not in listing_queue: listing_queue.append(candidate)
        print(f"LISTING {fetch_count}/{MAX_LISTING_REQUESTS}: +{added}; total new {len(discovered)}")
        time.sleep(0.05)

    # Validate and preserve the previous order, with every discovered URL appended exactly once.
    final_lines = existing_lines + list(discovered.values())
    final_keys = {normal_key(line) for line in final_lines if normalize_product(line)}
    print(f"RESULT existing_lines={len(existing_lines)} existing_unique={len(existing_keys)} added={len(discovered)} total_unique={len(final_keys)}")
    if len(final_keys) < MIN_TOTAL:
        print(f"Safety stop: only {len(final_keys)} unique product URLs; existing LINKS was not changed.", file=sys.stderr)
        return 1
    updated_text = "\n".join(final_lines) + "\n"
    payload = {
        "message": f"Add {len(discovered)} more direct KaBuM product URLs ({len(final_keys)} unique)",
        "content": base64.b64encode(updated_text.encode("utf-8")).decode("ascii"),
        "sha": current["sha"], "branch": "main",
    }
    try:
        req = urllib.request.Request(GITHUB_CONTENTS, data=json.dumps(payload).encode("utf-8"),
            headers={**gh_headers,"Content-Type":"application/json"}, method="PUT")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            saved = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"GitHub update failed: {exc}", file=sys.stderr); return 1
    print(f"SUCCESS: LINKS now contains {len(final_keys)} unique direct product URLs; added {len(discovered)}.")
    print(saved.get("commit",{}).get("html_url","Commit created."))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
