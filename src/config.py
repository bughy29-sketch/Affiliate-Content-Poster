"""Configurare încărcată din variabile de mediu."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # opțional: încarcă .env doar dacă e instalat
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

DEFAULT_DISCLOSURE = (
    "Conține linkuri de afiliere. Putem primi un comision fără cost suplimentar pentru tine."
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} trebuie să fie întreg, primit {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    client_id: str
    client_secret: str
    refresh_token: str
    default_board_id: str
    dry_run: bool
    max_pins_per_run: int
    min_delay_seconds: int
    max_delay_seconds: int
    disclosure: str
    queue_path: str
    state_path: str

    @classmethod
    def from_env(cls) -> "Config":
        if load_dotenv is not None:
            load_dotenv()  # nu suprascrie variabilele deja setate
        disclosure = (os.getenv("AFFILIATE_DISCLOSURE") or "").strip() or DEFAULT_DISCLOSURE
        config = cls(
            client_id=(os.getenv("PINTEREST_CLIENT_ID") or "").strip(),
            client_secret=(os.getenv("PINTEREST_CLIENT_SECRET") or "").strip(),
            refresh_token=(os.getenv("PINTEREST_REFRESH_TOKEN") or "").strip(),
            default_board_id=(os.getenv("PINTEREST_BOARD_ID") or "").strip(),
            dry_run=_env_bool("DRY_RUN", True),
            max_pins_per_run=_env_int("MAX_PINS_PER_RUN", 3),
            min_delay_seconds=_env_int("MIN_DELAY_SECONDS", 30),
            max_delay_seconds=_env_int("MAX_DELAY_SECONDS", 90),
            disclosure=disclosure,
            queue_path=(os.getenv("QUEUE_PATH") or "data/queue.json").strip(),
            state_path=(os.getenv("STATE_PATH") or "data/state.json").strip(),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.max_pins_per_run < 1:
            raise ValueError("MAX_PINS_PER_RUN trebuie să fie >= 1")
        if self.min_delay_seconds < 0:
            raise ValueError("MIN_DELAY_SECONDS nu poate fi negativ")
        if self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("MAX_DELAY_SECONDS trebuie să fie >= MIN_DELAY_SECONDS")

        if not self.dry_run:
            missing = [
                name
                for name, value in (
                    ("PINTEREST_CLIENT_ID", self.client_id),
                    ("PINTEREST_CLIENT_SECRET", self.client_secret),
                    ("PINTEREST_REFRESH_TOKEN", self.refresh_token),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "Lipsesc credențiale pentru rularea reală: "
                    + ", ".join(missing)
                    + " (folosește DRY_RUN=true pentru validare)"
                )
