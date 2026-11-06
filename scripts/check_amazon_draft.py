#!/usr/bin/env python3
"""Verifică schița locală de pinuri Amazon: data/amazon.local.txt.

Nu publică nimic. Verifică doar că fiecare slot are nume, link valid cu tag
și imagine în images/. Rulează: python scripts/check_amazon_draft.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

DRAFT_PATH = Path("data/amazon.local.txt")
IMAGE_DIR = Path("images")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
SLOT_RE = re.compile(r"^\d{3}$")


def _mask(value: str) -> str:
    return value[:3] + "..." + value[-3:] if len(value) > 6 else "***"


def _env_tag() -> str:
    if load_dotenv is not None:
        load_dotenv()
    return (os.getenv("AMAZON_TAG") or "").strip()


def _parse() -> list[tuple[int, str, str, str]]:
    rows = []
    for number, raw in enumerate(DRAFT_PATH.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        parts += [""] * (3 - len(parts))
        rows.append((number, parts[0], parts[1], parts[2]))
    return rows


def _find_image(slot: str) -> Path | None:
    for ext in IMAGE_EXTS:
        candidate = IMAGE_DIR / f"amazon-{slot}{ext}"
        if candidate.exists():
            return candidate
    return None


def _check_link(link: str, env_tag: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not link:
        errors.append("link lipsă")
        return errors, warnings

    parsed = urlparse(link)
    if parsed.scheme != "https":
        errors.append("linkul trebuie să folosească https://")

    host = (parsed.hostname or "").lower()
    if host == "amzn.to":
        warnings.append("link amzn.to — verifică în consola Amazon că duce la produsul dorit")
    elif not (host.startswith("amazon.") or ".amazon." in host):
        errors.append(f"hostul nu e Amazon ({host or 'gol'})")
    else:
        tag = (parse_qs(parsed.query).get("tag") or [""])[0].strip()
        if not tag:
            errors.append("linkul nu are parametrul ?tag=")
        elif env_tag and tag != env_tag:
            warnings.append(
                f"tagul din link ({_mask(tag)}) diferă de AMAZON_TAG ({_mask(env_tag)})"
            )

    return errors, warnings


def main() -> int:
    if not DRAFT_PATH.exists():
        print(f"Lipsește {DRAFT_PATH}.", file=sys.stderr)
        return 2

    env_tag = _env_tag()
    if not env_tag:
        print("Atenție: AMAZON_TAG e gol în .env — nu pot compara tagul.", file=sys.stderr)

    rows = _parse()
    if not rows:
        print("Fișierul nu are nicio linie de completat.")
        return 2

    incomplete = 0
    problems = 0

    for _line, slot, name, link in rows:
        errors: list[str] = []
        warnings: list[str] = []

        if not SLOT_RE.match(slot):
            errors.append("numărul trebuie să fie de forma 001")
            slot = slot or "???"

        if not name:
            errors.append("numele produsului lipsește")

        link_errors, link_warnings = _check_link(link, env_tag)
        errors += link_errors
        warnings += link_warnings

        image = _find_image(slot)
        if image is None:
            errors.append(f"lipsește images/amazon-{slot}.jpg")

        if errors:
            incomplete += 1
            problems += 1
            print(f"[{slot}] INCOMPLET — {name or '(fără nume)'}")
            for error in errors:
                print(f"    - {error}")
        else:
            print(f"[{slot}] OK — {name}")
            print(f"    imagine: {image.as_posix()}")

        for warning in warnings:
            print(f"    ! {warning}")

    print()
    if incomplete:
        print(f"{incomplete} slot(uri) incomplete din {len(rows)}.")
        print("Nu se publică nimic până nu sunt complete.")
        return 1

    print(f"Toate cele {len(rows)} sloturi sunt complete.")
    print("Următorul pas: îmi spui „gata” și le adaug în coadă (enabled: false).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
