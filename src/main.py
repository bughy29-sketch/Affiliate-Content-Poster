"""Orchestrator: validează coada și publică pinurile eligibile."""

from __future__ import annotations

import logging
import random
import sys
import time
from datetime import datetime, timezone

from .config import Config
from .pinterest import PinterestClient, PinterestError
from .queue import is_due, load_queue, load_state, save_state
from .validate import build_description, detect_affiliate, validate_pin

log = logging.getLogger("pins")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def _pin_id(pin: dict) -> str:
    return str(pin.get("id") or "").strip()


def _board_id(pin: dict, config: Config) -> str:
    return str(pin.get("board_id") or config.default_board_id or "").strip()


def _collect_candidates(
    pins: list[dict],
    config: Config,
    now: datetime,
    state: dict,
) -> tuple[list[dict], int]:
    posted = state["posted"]
    failures = state["failures"]

    candidates: list[dict] = []
    seen: set[str] = set()
    hard_errors = 0

    for pin in pins:
        pin_id = _pin_id(pin)
        if not pin_id:
            log.error("Pin fără id — ignorat: %r", pin.get("title"))
            hard_errors += 1
            continue

        if pin_id in seen:
            log.error("[%s] id duplicat în coadă — ignorat", pin_id)
            hard_errors += 1
            continue
        seen.add(pin_id)

        if pin.get("enabled", True) is False:
            log.info("[%s] dezactivat — sărit", pin_id)
            continue

        if pin_id in posted:
            log.info("[%s] deja publicat — sărit", pin_id)
            continue

        result = validate_pin(pin, config)
        for warning in result.warnings:
            log.warning("[%s] %s", pin_id, warning)

        if not result.ok:
            for error in result.errors:
                log.error("[%s] %s", pin_id, error)
            failures[pin_id] = {
                "at": now.isoformat(),
                "stage": "validation",
                "errors": result.errors,
            }
            hard_errors += 1
            continue

        try:
            due = is_due(pin, now)
        except ValueError as exc:
            log.error("[%s] %s", pin_id, exc)
            hard_errors += 1
            continue

        if not due:
            log.info(
                "[%s] programat pentru %s — nu e încă eligibil",
                pin_id,
                pin.get("scheduled_at"),
            )
            continue

        candidates.append(pin)

    candidates.sort(key=lambda item: str(item.get("scheduled_at") or ""))
    return candidates, hard_errors


def main() -> int:
    _setup_logging()

    try:
        config = Config.from_env()
        pins = load_queue(config.queue_path)
        state = load_state(config.state_path)
    except (ValueError, FileNotFoundError) as exc:
        log.error("Configurare/coadă invalidă: %s", exc)
        return 2

    now = datetime.now(timezone.utc)
    candidates, hard_errors = _collect_candidates(pins, config, now, state)
    batch = candidates[: config.max_pins_per_run]

    log.info(
        "Rulare: %d în coadă, %d eligibile, %d selectate, dry_run=%s",
        len(pins),
        len(candidates),
        len(batch),
        config.dry_run,
    )

    if not batch:
        if not config.dry_run:
            save_state(config.state_path, state)
        return 1 if hard_errors else 0

    if config.dry_run:
        for pin in batch:
            pin_id = _pin_id(pin)
            affiliate = (
                (pin.get("affiliate") or "").strip()
                or detect_affiliate(str(pin.get("link") or ""))
            )
            log.info(
                "[%s] DRY RUN — ar publica pe board %s | afiliere=%s | link=%s",
                pin_id,
                _board_id(pin, config),
                affiliate or "-",
                pin.get("link"),
            )
            log.info("[%s] descriere finală:\n%s", pin_id, build_description(pin, config))
        return 1 if hard_errors else 0

    client = PinterestClient(
        client_id=config.client_id,
        client_secret=config.client_secret,
        refresh_token=config.refresh_token,
    )

    published = 0
    api_errors = 0

    for index, pin in enumerate(batch):
        pin_id = _pin_id(pin)
        try:
            response = client.create_pin(
                board_id=_board_id(pin, config),
                title=str(pin.get("title") or "").strip(),
                description=build_description(pin, config),
                link=str(pin.get("link") or "").strip(),
                image_url=str(pin.get("image_url") or "").strip(),
                alt_text=str(pin.get("alt_text") or "").strip(),
            )
            state["posted"][pin_id] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "pin_id": response.get("id"),
                "board_id": _board_id(pin, config),
            }
            state["failures"].pop(pin_id, None)
            published += 1
            log.info("[%s] publicat (pin_id=%s)", pin_id, response.get("id"))
        except PinterestError as exc:
            api_errors += 1
            state["failures"][pin_id] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "stage": "api",
                "error": str(exc),
            }
            log.error("[%s] publicare eșuată: %s", pin_id, exc)

        if index < len(batch) - 1:
            delay = random.uniform(config.min_delay_seconds, config.max_delay_seconds)
            log.info("Pauză %.1fs înainte de următorul pin", delay)
            time.sleep(delay)

    save_state(config.state_path, state)
    log.info(
        "Gata: %d publicate, %d erori API, %d erori de validare",
        published,
        api_errors,
        hard_errors,
    )
    return 1 if (hard_errors or api_errors) else 0


if __name__ == "__main__":
    sys.exit(main())
