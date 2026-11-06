#!/usr/bin/env python3
"""Inspectează structura unui feed Profitshare fără a afișa URL-ul.

Citește PROFITSHARE_FEED_URL din .env și afișează formatul, coloanele și
primele 2 înregistrări, ca să putem scrie importatorul corect.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

MAX_BYTES = 300 * 1024 * 1024


def _download_http(url: str) -> bytes:
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        buffer = io.BytesIO()
        total = 0
        for chunk in response.iter_content(256 * 1024):
            total += len(chunk)
            if total > MAX_BYTES:
                raise SystemExit("Feed-ul depășește 300 MB; opresc pentru siguranță.")
            buffer.write(chunk)
    return buffer.getvalue()


def _read_source(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        path = unquote(parsed.path) if parsed.scheme == "file" else url
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        data = Path(path).read_bytes()
    elif parsed.scheme in ("http", "https"):
        data = _download_http(url)
    else:
        raise SystemExit(f"Schemă nesuportată: {parsed.scheme or '(gol)'}")

    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def _short(value: str, limit: int = 160) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _inspect_xml(data: bytes) -> None:
    count = 0
    for _event, element in ET.iterparse(io.BytesIO(data), events=("end",)):
        if len(element) == 0:
            continue
        print(f"Element: <{element.tag}>")
        for child in element:
            print(f"  <{child.tag}> = {_short(child.text or '')}")
        if element.attrib:
            print(f"  atribute: {element.attrib}")
        count += 1
        element.clear()
        if count >= 2:
            break
    if count == 0:
        print("Nu am găsit elemente cu date.")


def _inspect_csv(data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:10000], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, None)
    print("Delimiter:", repr(delimiter))
    print("Coloane:", header)
    for index, row in enumerate(reader):
        if index >= 2:
            break
        print(f"Rând {index + 1}:")
        for name, value in zip(header or [], row):
            print(f"  {name} = {_short(value)}")


def _inspect_json(data: bytes) -> None:
    payload = json.loads(data.decode("utf-8", errors="replace"))
    if isinstance(payload, dict):
        print("Chei obiect:", list(payload.keys()))
        for key, value in payload.items():
            if isinstance(value, list):
                print(f"Lista '{key}': {len(value)} elemente")
                if value:
                    print(json.dumps(value[0], indent=2, ensure_ascii=False)[:2000])
                return
        print(json.dumps(payload, indent=2, ensure_ascii=False)[:2000])
    elif isinstance(payload, list):
        print(f"Listă: {len(payload)} elemente")
        if payload:
            print(json.dumps(payload[0], indent=2, ensure_ascii=False)[:2000])


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    url = (os.getenv("PROFITSHARE_FEED_URL") or "").strip()
    if not url:
        print("Setează PROFITSHARE_FEED_URL în .env.", file=sys.stderr)
        return 2

    print("Citesc feed-ul (calea/URL-ul nu este afișat)...")
    data = _read_source(url)
    print(f"Citit: {len(data) / 1024 / 1024:.1f} MB")

    head = data.lstrip()[:1]
    if head == b"<":
        print("Format detectat: XML")
        _inspect_xml(data)
    elif head in (b"[", b"{"):
        print("Format detectat: JSON")
        _inspect_json(data)
    else:
        print("Format detectat: CSV / text")
        _inspect_csv(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
