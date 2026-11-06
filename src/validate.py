"""Reguli de conformitate și igienă aplicate fiecărui pin."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from .config import Config
from .queue import parse_iso

MAX_TITLE = 100
MAX_DESCRIPTION = 500
MAX_URL = 2048

# Scurtătoare folosite frecvent pentru cloaking de linkuri de afiliere.
SHORTENER_HOSTS = {
    "bit.ly",
    "tinyurl.com",
    "cutt.ly",
    "shorturl.at",
    "rb.gy",
    "is.gd",
    "t.co",
    "ow.ly",
    "buff.ly",
    "rebrand.ly",
}


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def detect_affiliate(link: str) -> str:
    host = (urlparse(link).hostname or "").lower()
    if host == "amzn.to" or host.startswith("amazon.") or ".amazon." in host:
        return "amazon"
    if host == "profitshare.ro" or host.endswith(".profitshare.ro"):
        return "emag"
    return ""


def build_description(pin: dict, config: Config) -> str:
    """Adaugă disclosure-ul o singură dată, dacă pinul are afiliere."""
    description = str(pin.get("description") or "").strip()
    affiliate = (
        (pin.get("affiliate") or "").strip().lower()
        or detect_affiliate(str(pin.get("link") or ""))
    )
    disclosure = str(pin.get("disclosure") or config.disclosure).strip()
    if affiliate and disclosure and disclosure.lower() not in description.lower():
        description = f"{description}\n\n{disclosure}".strip()
    return description


def validate_pin(pin: dict, config: Config) -> CheckResult:
    result = CheckResult()

    pin_id = str(pin.get("id") or "").strip()
    title = str(pin.get("title") or "").strip()
    link = str(pin.get("link") or "").strip()
    image_url = str(pin.get("image_url") or "").strip()
    board_id = str(pin.get("board_id") or config.default_board_id or "").strip()
    raw_description = str(pin.get("description") or "").strip()
    description = build_description(pin, config)

    if not pin_id:
        result.errors.append("id lipsește")

    if not board_id:
        result.errors.append("board_id lipsește (pin sau PINTEREST_BOARD_ID)")
    elif not board_id.isdigit():
        result.errors.append("board_id trebuie să fie numeric")

    if not title:
        result.errors.append("title lipsește")
    elif len(title) > MAX_TITLE:
        result.errors.append(f"title depășește {MAX_TITLE} caractere ({len(title)})")

    if not raw_description:
        result.errors.append("description lipsește")
    elif len(description) > MAX_DESCRIPTION:
        result.errors.append(
            f"description finală depășește {MAX_DESCRIPTION} caractere ({len(description)})"
        )

    _check_url(link, "link", result)
    _check_url(image_url, "image_url", result)

    if link:
        host = (urlparse(link).hostname or "").lower()
        if host in SHORTENER_HOSTS:
            result.errors.append(
                f"link folosește scurtător interzis ({host}) — risc de cloaking"
            )

        affiliate = (pin.get("affiliate") or "").strip().lower() or detect_affiliate(link)
        if affiliate == "amazon":
            _check_amazon(link, host, result)
        elif affiliate == "emag":
            _check_emag(host, result)

    if pin.get("scheduled_at"):
        try:
            parse_iso(pin["scheduled_at"])
        except ValueError as exc:
            result.errors.append(str(exc))

    return result


def _check_url(value: str, name: str, result: CheckResult) -> None:
    if not value:
        result.errors.append(f"{name} lipsește")
        return
    if len(value) > MAX_URL:
        result.errors.append(f"{name} depășește {MAX_URL} caractere")
    parsed = urlparse(value)
    if parsed.scheme != "https":
        result.errors.append(f"{name} trebuie să folosească https://")
    if not parsed.hostname:
        result.errors.append(f"{name} nu are host valid")


def _check_amazon(link: str, host: str, result: CheckResult) -> None:
    if host == "amzn.to":
        result.warnings.append(
            "link amzn.to: verifică în consola Amazon Associates că tag-ul e corect"
        )
        return

    if not (host.startswith("amazon.") or ".amazon." in host):
        result.errors.append(f"link declarat Amazon, dar hostul e {host or 'necunoscut'}")
        return

    query = parse_qs(urlparse(link).query)
    if not (query.get("tag") or [""])[0].strip():
        result.errors.append("link Amazon fără parametrul 'tag'")


def _check_emag(host: str, result: CheckResult) -> None:
    if not (host == "profitshare.ro" or host.endswith(".profitshare.ro")):
        result.warnings.append(
            "link eMAG nu e pe profitshare.ro "
            f"(host: {host or 'necunoscut'}) — verifică tracking-ul"
        )
