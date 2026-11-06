#!/usr/bin/env python3
"""Importă produse din feed-ul Profitshare în coada de pinuri.

Exemple:
    python scripts/import_profitshare_feed.py --list-categories
    python scripts/import_profitshare_feed.py --limit 5 --max-per-category 1
    python scripts/import_profitshare_feed.py --limit 10 --include telefon laptop
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

MAX_BYTES = 300 * 1024 * 1024
MAX_TITLE = 100
MAX_DESCRIPTION = 500
DISCLOSURE_RESERVE = 120

PRICE_RE = re.compile(
    r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?\s*(?:lei|ron|eur|€)\b",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZĂÂÎȘȚ„\"(])")

BENEFITS = [
    ("telefon", "utilizarea de zi cu zi"),
    ("laptop", "muncă și studiu"),
    ("notebook", "muncă și studiu"),
    ("tablet", "conținut și mobilitate"),
    ("monitor", "birou și productivitate"),
    ("casc", "muzică și apeluri"),
    ("audio", "muzică și apeluri"),
    ("box", "muzică și film"),
    ("gaming", "sesiuni de gaming"),
    ("smartwatch", "activitate zilnică"),
    ("ssd", "un upgrade de viteză"),
    ("router", "o rețea stabilă acasă"),
    ("camera", "fotografie și video"),
    ("drone", "fotografie aeriană"),
    ("tv", "film și seriale"),
    ("televizor", "film și seriale"),
]

TEMPLATES = [
    "{name} — o opțiune de luat în calcul pentru {benefit}. Detalii și disponibilitate în magazin.",
    "Idee de achiziție: {name}. Verifică specificațiile și disponibilitatea înainte de comandă.",
    "{name}, din categoria {category}: potrivit pentru {benefit}.",
    "Dacă vrei {benefit}, {name} merită o privire. Găsești detaliile complete în magazin.",
]


def _read_source(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        path = unquote(parsed.path) if parsed.scheme == "file" else url
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        data = Path(path).read_bytes()
    elif parsed.scheme in ("http", "https"):
        with requests.get(url, stream=True, timeout=180) as response:
            response.raise_for_status()
            buffer = io.BytesIO()
            total = 0
            for chunk in response.iter_content(256 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise SystemExit("Feed-ul depășește 300 MB; opresc.")
                buffer.write(chunk)
        data = buffer.getvalue()
    else:
        raise SystemExit(f"Schemă nesuportată: {parsed.scheme or '(gol)'}")

    if data[:2] == b"\x1f\x8b":
        import gzip

        data = gzip.decompress(data)
    return data


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_products(data: bytes):
    for _event, element in ET.iterparse(io.BytesIO(data), events=("end",)):
        if _local_name(element.tag) != "product":
            continue
        record = {}
        for child in element:
            record[_local_name(child.tag)] = (child.text or "").strip()
        element.clear()
        yield record


def _normalize(value: str) -> str:
    text = html.unescape(value or "")
    text = TAG_RE.sub(" ", text)
    text = text.replace("\xa0", " ")
    text = PRICE_RE.sub(" ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" -–—,;:")


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" -–—,;:")
    return cut + "…"


def _clean(value: str, limit: int) -> str:
    return _clip(_normalize(value), limit)


def _summarize(value: str, budget: int) -> str:
    """Păstrează doar propoziții întregi, ca descrierea să nu se rupă la mijloc."""
    text = _normalize(value)
    if not text:
        return ""

    sentences = [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]
    summary = ""
    for sentence in sentences:
        candidate = f"{summary} {sentence}".strip()
        if len(candidate) > budget:
            break
        summary = candidate
        if len(summary) >= budget * 0.6:
            break

    if not summary:
        summary = _clip(text, budget)
    if summary[-1] not in ".!?…":
        summary += "…"
    return summary


def _normalize_affiliate(raw: str) -> str:
    value = (raw or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return ""
    host = (parsed.hostname or "").lower()
    if not (host == "profitshare.ro" or host.endswith(".profitshare.ro")):
        return ""
    if parsed.scheme == "http":
        value = "https://" + value[len("http://") :]
    return value


def _price(record: dict) -> float:
    for key in ("price_discounted", "price_vat", "price_no_vat"):
        raw = (record.get(key) or "").strip()
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return 0.0


def _benefit(record: dict) -> str:
    haystack = f"{record.get('category', '')} {record.get('product_name', '')}".lower()
    for key, label in BENEFITS:
        if key in haystack:
            return label
    return "utilizarea de zi cu zi"


def _build_id(record: dict) -> str:
    basis = f"{record.get('adv_name', '')}|{record.get('product_code', '')}|{record.get('link', '')}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
    return f"emag-{digest}"


def _build_description(record: dict, mode: str) -> str:
    name = _clean(record.get("product_name", ""), 90)
    category = _clean(record.get("category", ""), 40)
    benefit = _benefit(record)

    if mode == "feed":
        feed_text = _summarize(
            record.get("product_desc", ""), MAX_DESCRIPTION - DISCLOSURE_RESERVE
        )
        if len(feed_text) >= 80:
            return feed_text
    elif mode != "template":
        raise SystemExit(f"Mod de descriere necunoscut: {mode}")

    template = TEMPLATES[int(_build_id(record)[-2:], 16) % len(TEMPLATES)]
    return template.format(name=name or "Produsul", benefit=benefit, category=category or "produse tech")


def _select(products, args):
    if args.pick:
        return _select_picked(products, args)

    selected = []
    per_category: Counter = Counter()
    seen_names: set[str] = set()

    for record in products:
        if len(selected) >= args.limit:
            break
        if args.in_stock_only and (record.get("availability") or "").lower() != "in_stock":
            continue

        category = (record.get("category") or "").strip().lower()
        name = (record.get("product_name") or "").strip()
        haystack = f"{category} {name}".lower()

        if args.exclude and any(word.lower() in haystack for word in args.exclude):
            continue
        if args.include and not any(word.lower() in haystack for word in args.include):
            continue

        price = _price(record)
        if args.min_price is not None and price < args.min_price:
            continue
        if args.max_price is not None and price > args.max_price:
            continue

        if not _normalize_affiliate(record.get("product_aff_link", "")):
            continue
        image = (record.get("product_pic") or "").strip()
        if not image.startswith("https://"):
            continue
        if not name:
            continue
        if name.lower() in seen_names:
            continue
        if per_category[category] >= args.max_per_category:
            continue

        seen_names.add(name.lower())
        per_category[category] += 1
        selected.append(record)

    return selected


def _select_picked(products, args):
    """Selectează produsele exacte cerute prin --pick, în ordinea dată."""
    by_code: dict[str, dict] = {}
    for record in products:
        code = (record.get("product_code") or "").strip()
        if code and code not in by_code:
            by_code[code] = record

    picked = []
    for code in args.pick:
        record = by_code.get(code)
        if record is None:
            print(f"AVERTISMENT: codul {code} nu există în feed — sărit", file=sys.stderr)
            continue
        name = (record.get("product_name") or "").strip()
        image = (record.get("product_pic") or "").strip()
        if args.in_stock_only and (record.get("availability") or "").lower() != "in_stock":
            print(f"AVERTISMENT: {code} nu e în stoc — sărit", file=sys.stderr)
            continue
        if not name or not image.startswith("https://"):
            print(f"AVERTISMENT: {code} nu are nume/imagine validă — sărit", file=sys.stderr)
            continue
        if not _normalize_affiliate(record.get("product_aff_link", "")):
            print(f"AVERTISMENT: {code} nu are link Profitshare valid — sărit", file=sys.stderr)
            continue
        picked.append(record)
    return picked


def _build_pins(records, args) -> list[dict]:
    start = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    start = start + timedelta(days=args.start_days_ahead)

    pins = []
    for index, record in enumerate(records):
        scheduled = start + timedelta(days=index * args.days_between)
        pins.append(
            {
                "id": _build_id(record),
                "board_id": args.board_id,
                "title": _clean(record.get("product_name", ""), MAX_TITLE),
                "description": _build_description(record, args.description_mode),
                "link": _normalize_affiliate(record.get("product_aff_link", "")),
                "image_url": (record.get("product_pic") or "").strip(),
                "alt_text": _clean(record.get("product_name", ""), 120),
                "scheduled_at": scheduled.isoformat().replace("+00:00", "Z"),
                "affiliate": "emag",
                "enabled": args.enable,
            }
        )
    return pins


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", default=os.getenv("PROFITSHARE_FEED_URL", ""))
    parser.add_argument("--output", default="data/queue.json")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-per-category", type=int, default=1)
    parser.add_argument("--include", nargs="*", default=[])
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument(
        "--pick",
        nargs="*",
        default=[],
        help="coduri de produs exacte, în ordinea dorită (ignoră celelalte filtre)",
    )
    parser.add_argument("--min-price", type=float)
    parser.add_argument("--max-price", type=float)
    parser.add_argument("--in-stock-only", action="store_true", default=True)
    parser.add_argument("--allow-out-of-stock", dest="in_stock_only", action="store_false")
    parser.add_argument("--description-mode", choices=["feed", "template"], default="feed")
    parser.add_argument("--start-days-ahead", type=int, default=1)
    parser.add_argument("--days-between", type=int, default=1)
    parser.add_argument("--board-id", default=os.getenv("PINTEREST_BOARD_ID", ""))
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--list-categories", action="store_true")
    args = parser.parse_args()

    if not args.feed:
        print("Setează PROFITSHARE_FEED_URL în .env sau folosește --feed.", file=sys.stderr)
        return 2

    data = _read_source(args.feed)
    products = list(_iter_products(data))
    print(f"Produse în feed: {len(products)}")

    if args.list_categories:
        counts = Counter((p.get("category") or "(fără categorie)").strip() for p in products)
        for category, count in counts.most_common(50):
            print(f"{count:5d}  {category}")
        return 0

    selected = _select(products, args)
    if not selected:
        print("Niciun produs nu a trecut de filtre.", file=sys.stderr)
        return 1

    pins = _build_pins(selected, args)

    output = Path(args.output)
    if args.merge and output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        existing_pins = existing.get("pins", []) if isinstance(existing, dict) else existing
        existing_ids = {pin.get("id") for pin in existing_pins}
        pins = [pin for pin in pins if pin["id"] not in existing_ids] + existing_pins
        # păstrează ordinea cronologică, ca fișierul să fie ușor de verificat
        pins.sort(key=lambda pin: (str(pin.get("scheduled_at") or ""), str(pin.get("id") or "")))
    else:
        existing_ids = set()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"pins": pins}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Scrise {len(pins)} pinuri în {output} (enabled={args.enable}).")
    for pin in pins[: args.limit]:
        print(f"- [{pin['id']}] {pin['title']}")
    if existing_ids:
        print(f"({len(existing_ids)} id-uri existente au fost păstrate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
