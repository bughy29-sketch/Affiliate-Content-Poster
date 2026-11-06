"""Încărcarea cozii de conținut și a stării persistente."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_iso(value: Any) -> datetime | None:
    """Parsează un timestamp ISO 8601; naiv = UTC."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"scheduled_at invalid: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_queue(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Coada nu există: {file_path}")
    data = json.loads(file_path.read_text(encoding="utf-8"))
    pins = data.get("pins", []) if isinstance(data, dict) else data
    if not isinstance(pins, list):
        raise ValueError("Coada trebuie să conțină o listă 'pins'")
    return [pin for pin in pins if isinstance(pin, dict)]


def load_state(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {"posted": {}, "failures": {}}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Starea nu e JSON valid: {file_path}") from exc
    if not isinstance(data, dict):
        raise ValueError("Starea trebuie să fie un obiect JSON")
    data.setdefault("posted", {})
    data.setdefault("failures", {})
    return data


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def is_due(pin: dict[str, Any], now: datetime) -> bool:
    scheduled = parse_iso(pin.get("scheduled_at"))
    return scheduled is None or scheduled <= now
