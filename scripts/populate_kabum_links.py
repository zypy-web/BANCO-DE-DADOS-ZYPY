#!/usr/bin/env python3
"""Collect direct product URLs from KaBuM!'s public app catalog and append them to LINKS.

This runs only when the one-time workflow file is added. It preserves existing
lines, removes duplicates among new URLs, and refuses to commit unless LINKS has
more than 500 unique product URLs.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

OWNER = "zypy-web"
REPO = "BANCO-DE-DADOS-ZYPY"
FILE_PATH = "LINKS"
API_BASE = "https://servicespub.prod.api.aws.grupokabum.com.br/home/v1/home/produto"
GITHUB_CONTENTS = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{FILE_PATH}"
MIN_TOTAL = 501
MAX_PAGES = 50
PAGE_SIZE = 100


def http_json(url: str, headers: dict[str, str] | None = None):
    req_headers = {
        "User-Agent": "ZYPY-KaBuM-Link-Collector/1.0",
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers)
    with urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")[:180].strip("-")


def product_url(product: dict) -> str | None:
    raw = product.get("link_descricao") or product.get("url") or product.get("link") or ""
    if isinstance(raw, str) and raw.strip():
        raw = raw.strip()
        if raw.startswith("//"):
            raw = "https:" + raw
        elif raw.startswith("/"):
            raw = "https://www.kabum.com.br" + raw
        elif raw.startswith("www.kabum.com.br/"):
            raw = "https://" + raw
        parsed = urlparse(raw)
        if parsed.hostname and parsed.hostname.lower().endswith("kabum.com.br") and "/produto/" in parsed.path:
            cleaned = urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
            if re.search(r"/produto/\d+", cleaned):
                return cleaned

    code = product.get("codigo") or product.get("id") or product.get("product_id")
    name = product.get("nome") or product.get("name") or product.get("titulo") or ""
    if code and str(code).isdigit() and name:
        return f"https://www.kabum.com.br/produto/{code}/{slugify(str(name))}"
    return None


def normal_key(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.path:
        return url.strip().rstrip("/")
    host = (parsed.hostname or "").lower()
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return f"https://{host}{path}".lower()


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Missing GITHUB_TOKEN.", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    current = http_json(GITHUB_CONTENTS, headers)
    sha = current.get("sha")
    try:
        existing_text = base64.b64decode(current["content"]).decode("utf-8")
    except Exception:
        print("Could not decode current LINKS file; refusing to overwrite.", file=sys.stderr)
        return 1

    existing_lines = [line.strip() for line in existing_text.splitlines() if line.strip()]
    existing_keys = {normal_key(line) for line in existing_lines}
    discovered: list[str] = []
    discovered_keys: set[str] = set()
    seen_product_ids: set[str] = set()
    empty_pages = 0

    for page in range(1, MAX_PAGES + 1):
        url = f"{API_BASE}?app=1&limite={PAGE_SIZE}&pagina={page}"
        try:
            payload = http_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Page {page} failed: {exc}", file=sys.stderr)
            # Stop safely rather than writing a partial/truncated catalog.
            return 1

        products = payload.get("produtos", []) if isinstance(payload, dict) else []
        if not isinstance(products, list) or not products:
            empty_pages += 1
            if empty_pages >= 1:
                print(f"No products on page {page}; pagination ended.")
                break
            continue

        page_added = 0
        for product in products:
            if not isinstance(product, dict):
                continue
            code = str(product.get("codigo") or product.get("id") or "")
            if code and code in seen_product_ids:
                continue
            if code:
                seen_product_ids.add(code)
            link = product_url(product)
            if not link:
                continue
            key = normal_key(link)
            if key in existing_keys or key in discovered_keys:
                continue
            if "kabum.com.br" not in urlparse(link).netloc.lower() or "/produto/" not in urlparse(link).path:
                continue
            discovered.append(link)
            discovered_keys.add(key)
            page_added += 1

        print(f"Page {page}: {len(products)} records, {page_added} new product URLs, total new {len(discovered)}.")
        if len(existing_keys | discovered_keys) >= MIN_TOTAL:
            break
        if page_added == 0:
            empty_pages += 1
            if empty_pages >= 3:
                print("Three consecutive pages yielded no new product URLs; stopping.")
                break
        else:
            empty_pages = 0
        time.sleep(0.25)

    final_lines = existing_lines + discovered
    final_keys = {normal_key(line) for line in final_lines}
    if len(final_keys) < MIN_TOTAL:
        print(
            f"Safety stop: only {len(final_keys)} unique product URLs found "
            f"({len(existing_lines)} existing + {len(discovered)} new); "
            f"required at least {MIN_TOTAL}. LINKS was not changed.",
            file=sys.stderr,
        )
        return 1

    updated_text = "\n".join(final_lines) + "\n"
    body = {
        "message": f"Add KaBuM product links (reach {len(final_keys)} unique URLs)",
        "content": base64.b64encode(updated_text.encode("utf-8")).decode("ascii"),
        "sha": sha,
        "branch": "main",
    }
    req = Request(
        GITHUB_CONTENTS,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"GitHub update failed: {exc}", file=sys.stderr)
        return 1

    print(f"SUCCESS: LINKS now contains {len(final_keys)} unique product URLs.")
    print(f"Added {len(discovered)} new direct product URLs.")
    print(result.get("commit", {}).get("html_url", "Commit created."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
