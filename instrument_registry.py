#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local instrument registry.

The registry is a local data file.  Unknown symbols are returned as unknown
instead of being guessed by AI or by heuristic asset-type inference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from price_provider import InvalidSymbolError, normalize_symbol


ROOT = Path(__file__).parent
DEFAULT_INSTRUMENT_REGISTRY_FILE = ROOT / "instruments.json"
VALID_ASSET_TYPES = {"common_stock", "etf", "fund", "adr", "cash", "unknown"}


class InstrumentRegistryError(Exception):
    """Instrument registry load/validation failed."""


@dataclass(frozen=True)
class Instrument:
    symbol: str
    display_name: str
    asset_type: str
    exchange: str
    currency: str
    data_source: str
    aliases: tuple[str, ...]
    verification_status: str = "confirmed"

    @property
    def search_terms(self) -> tuple[str, ...]:
        terms = [self.symbol, self.display_name, *self.aliases]
        normalized: list[str] = []
        seen: set[str] = set()
        for term in terms:
            clean = " ".join(str(term).strip().split())
            if clean and clean.lower() not in seen:
                seen.add(clean.lower())
                normalized.append(clean)
        return tuple(normalized)


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InstrumentRegistryError(f"instrument missing valid {key}")
    return value.strip()


def _parse_instrument(data: Any) -> Instrument:
    if not isinstance(data, dict):
        raise InstrumentRegistryError("instrument entry must be an object")
    try:
        symbol = normalize_symbol(_require_string(data, "symbol"))
    except InvalidSymbolError as exc:
        raise InstrumentRegistryError(f"invalid symbol: {data.get('symbol')!r}") from exc
    asset_type = _require_string(data, "asset_type")
    if asset_type not in VALID_ASSET_TYPES:
        raise InstrumentRegistryError(f"{symbol} invalid asset_type: {asset_type!r}")
    aliases = data.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(item, str) for item in aliases):
        raise InstrumentRegistryError(f"{symbol} aliases must be a list of strings")
    return Instrument(
        symbol=symbol,
        display_name=_require_string(data, "display_name"),
        asset_type=asset_type,
        exchange=_require_string(data, "exchange"),
        currency=_require_string(data, "currency"),
        data_source=_require_string(data, "data_source"),
        aliases=tuple(alias.strip() for alias in aliases if alias.strip()),
        verification_status=str(data.get("verification_status") or "confirmed"),
    )


def load_instrument_registry(
    path: str | Path = DEFAULT_INSTRUMENT_REGISTRY_FILE,
) -> dict[str, Instrument]:
    registry_path = Path(path)
    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InstrumentRegistryError(f"instrument registry not found: {registry_path}") from exc
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise InstrumentRegistryError(f"instrument registry cannot be read: {registry_path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("instruments"), list):
        raise InstrumentRegistryError("instrument registry must contain instruments array")

    instruments: dict[str, Instrument] = {}
    for raw in document["instruments"]:
        instrument = _parse_instrument(raw)
        if instrument.symbol in instruments:
            raise InstrumentRegistryError(f"duplicate instrument symbol: {instrument.symbol}")
        instruments[instrument.symbol] = instrument
    return instruments


def get_instrument(
    symbol: str,
    *,
    registry_path: str | Path = DEFAULT_INSTRUMENT_REGISTRY_FILE,
) -> Instrument | None:
    try:
        normalized = normalize_symbol(symbol)
    except InvalidSymbolError:
        return None
    return load_instrument_registry(registry_path).get(normalized)
