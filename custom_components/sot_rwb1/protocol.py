"""RWB1 dongle protocol codec.

Pure, dependency-free implementation of the wire protocol described in
rwb1_protocol_spec.md.  No Home Assistant or MQTT imports here so it can be
unit-tested in isolation.

Responsibilities
────────────────
* Build / parse the JSON envelope (spec §3).
* CRC-16/XMODEM write checksum (spec §7, CRACKED — verified against samples).
* Encode dev_rpc read / write `ci` payloads (spec §6.1).
* Format & validate setting values per channel (spec §6.3 / §6.4).
* Decode the base64 `co` telemetry frames into named values by *structural
  fingerprint*, because the `cn` channel aliases are scrambled per session
  (spec §5, §5.1 — aliases are not reliable, the frame shape is).
"""

from __future__ import annotations

import base64
import json
import random
import re
import string
from typing import Any

from .const import (
    SOLAR_CHARGING_SWITCH_ON,
)

# ──────────────────────────────────────────────────────────────────────────────
# CRC-16/XMODEM (spec §7)
# ──────────────────────────────────────────────────────────────────────────────


def crc16_xmodem(data: bytes) -> int:
    """CRC-16/XMODEM: poly 0x1021, init 0x0000, no reflection, xorout 0x0000.

    Verified against 75+ real samples in the spec (e.g. ``PBFT28.0`` -> ``b391``).
    """
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


# ──────────────────────────────────────────────────────────────────────────────
# JSON envelope (spec §3)
# ──────────────────────────────────────────────────────────────────────────────

_TOKEN_ALPHABET = string.ascii_letters + string.digits


def gen_token(length: int = 8) -> str:
    """An arbitrary ~8-char alphanumeric request token (spec §3, field `t`)."""
    return "".join(random.choices(_TOKEN_ALPHABET, k=length))


def gen_nonce(length: int = 9) -> str:
    """The per-message random `s` field (spec §3)."""
    return "".join(random.choices(_TOKEN_ALPHABET, k=length))


def build_envelope(c: int, body: dict[str, Any], i: int, token: str | None = None,
                   e: int | None = None) -> dict[str, Any]:
    """Assemble an outgoing envelope.  `e` is only set on replies/acks."""
    env: dict[str, Any] = {
        "c": c,
        "t": token or gen_token(),
        "s": gen_nonce(),
        "i": i,
        "b": body,
    }
    if e is not None:
        env["e"] = e
    return env


def encode_envelope(env: dict[str, Any]) -> bytes:
    """Serialize an envelope to compact JSON bytes for MQTT publish."""
    return json.dumps(env, separators=(",", ":")).encode("utf-8")


def parse_envelope(payload: bytes | str) -> dict[str, Any] | None:
    """Parse an incoming MQTT payload into an envelope dict, or None if invalid."""
    try:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", "replace")
        data = json.loads(payload)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# dev_rpc `ci` payload encoding (spec §6.1) and `co` decoding
# ──────────────────────────────────────────────────────────────────────────────


def build_read_ci(channel: str) -> str:
    """base64 of ``"<CHANNEL>\\r"`` — a pure read request (spec §6.1).

    e.g. ``HEEP1`` -> ``SEVFUDEN``.  No checksum on reads.
    """
    return base64.b64encode(f"{channel}\r".encode("ascii")).decode("ascii")


def build_write_ci(channel: str, value: str) -> str:
    """base64 of ``"<CHANNEL><VALUE><CRC16><\\r>"`` — a write request (spec §6.1/§7).

    The CRC is big-endian CRC-16/XMODEM over the ASCII of ``channel+value``
    (NOT including the trailing CR or the checksum bytes themselves).
    """
    data = f"{channel}{value}".encode("ascii")
    crc = crc16_xmodem(data)
    frame = data + crc.to_bytes(2, "big") + b"\r"
    return base64.b64encode(frame).decode("ascii")


def decode_co(co_b64: str) -> str:
    """base64-decode a `co` field into its ASCII text frame (spec §5/§6)."""
    raw = base64.b64decode(co_b64)
    return raw.decode("ascii", "replace")


def co_is_ack(co_b64: str) -> bool:
    """True if a write reply `co` indicates success (``(ACK..\\r``, spec §6.1)."""
    return "ACK" in decode_co(co_b64)


def co_is_nak(co_b64: str) -> bool:
    """True if a write reply `co` indicates rejection (``(NAK..\\r``, spec §6.1)."""
    return "NAK" in decode_co(co_b64)


# ──────────────────────────────────────────────────────────────────────────────
# Setting value formatting / validation (spec §6.3 / §6.4)
# ──────────────────────────────────────────────────────────────────────────────


def format_value(fmt: str, value: float, *, step5: bool = False) -> str:
    """Encode a numeric setting value into the dongle's on-wire string.

    Raises ValueError if `step5` is set and the value is not a multiple of 5
    (the firmware NAKs those, spec §6.4) — so we fail fast client-side rather
    than send a request the dongle will reject.
    """
    if step5 and int(round(value)) % 5 != 0:
        raise ValueError(f"value {value} must be a multiple of 5")

    if fmt == "v1":
        return f"{value:.1f}"
    if fmt == "v2":
        return f"{value:.2f}"
    if fmt == "i3":
        return f"{int(round(value)):03d}"
    if fmt == "i4":
        return f"{int(round(value)):04d}"
    raise ValueError(f"unknown value format {fmt!r}")


# ──────────────────────────────────────────────────────────────────────────────
# Telemetry frame decoding (spec §5) — structural fingerprinting
# ──────────────────────────────────────────────────────────────────────────────
#
# Each bulk-push / dump entry is ``{"cn": <scrambled alias>, "co": <base64>}``.
# `co` decodes to ``(<space-delimited fields>\r``.  Because `cn` is randomized
# per session, we identify which block is which from the *shape* of the fields,
# cross-referenced against the confirmed field maps in spec §5.1–§5.3.

_RE_VOLT3 = re.compile(r"^\d{3}\.\d$")       # 230.0, 292.6
_RE_2DOT1 = re.compile(r"^\d{2}\.\d$")       # 50.0, 00.5
_RE_INT2 = re.compile(r"^\d{2}$")            # 02
_RE_INT3 = re.compile(r"^\d{3}$")            # 264, 090
_RE_PVDOT = re.compile(r"^\d{4,}\.\d$")      # 00000.0  (PV field 3 marker)
_RE_TIME = re.compile(r"^\d{2}:\d{2}$")      # 23:15    (energy time marker)
_RE_DATE6 = re.compile(r"^\d{6}$")           # 260620
_RE_SIGNED = re.compile(r"^[+-]\d+$")        # +00371   (grid power marker)
_RE_LONGMASK = re.compile(r"^\d{8,}$")       # trailing status/fault mask


def _to_float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(s: str) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _split_frame(text: str) -> list[str]:
    """``(a b c\\r`` -> ``['a', 'b', 'c']``."""
    text = text.strip()
    if text.startswith("("):
        text = text[1:]
    text = text.rstrip("\r\n")
    return [f for f in text.split(" ") if f]


def _match_energy(f: list[str]) -> dict[str, Any] | None:
    # COST: 260620 23:15 15.204 0256.4 0449.4 000000449.4 000000000000
    if len(f) >= 6 and _RE_DATE6.match(f[0]) and _RE_TIME.match(f[1]):
        return {
            "energy_today": _to_float(f[2]),
            "energy_week": _to_float(f[3]),
            "energy_year": _to_float(f[4]),
            "energy_total": _to_float(f[5]),
        }
    return None


def _match_pv(f: list[str]) -> dict[str, Any] | None:
    # Mpod: 292.6 00.5 00147 00000.0 00000 2 292.6 015 05000
    if len(f) >= 7 and _RE_VOLT3.match(f[0]) and _RE_PVDOT.match(f[3]):
        return {
            "pv_voltage": _to_float(f[0]),
            "pv_current": _to_float(f[1]),
            "pv_power": _to_int(f[2]),
            "solar_charging_switch": f[5],
        }
    return None


def _match_load(f: list[str]) -> dict[str, Any] | None:
    # 2l0E: 230.0 50.0 00253 00169 007 420 03600 001.3 00003
    if (
        len(f) == 9
        and _RE_VOLT3.match(f[0])
        and _RE_2DOT1.match(f[1])
        and f[2].isdigit()
        and f[3].isdigit()
    ):
        return {
            "output_voltage": _to_float(f[0]),
            "output_frequency": _to_float(f[1]),
            "output_apparent_power": _to_int(f[2]),
            "output_active_power": _to_int(f[3]),
            "load_percent": _to_int(f[4]),
        }
    return None


def _match_grid(f: list[str]) -> dict[str, Any] | None:
    # WdRR: 238.4 50.0 264 090 65 45 +00371 0 03600 10+00000
    if len(f) == 10 and _RE_VOLT3.match(f[0]) and _RE_SIGNED.match(f[6]):
        return {
            "grid_voltage": _to_float(f[0]),
            "grid_frequency": _to_float(f[1]),
            "grid_power": _to_int(f[6]),
        }
    return None


def _match_battery(f: list[str]) -> dict[str, Any] | None:
    # 2ONL: 02 026.5 057 000 00009 366 000007100000 00000000
    if len(f) >= 5 and _RE_INT2.match(f[0]) and _RE_VOLT3.match(f[1]):
        return {
            "battery_count_series": _to_int(f[0]),
            "battery_voltage": _to_float(f[1]),
            "battery_soc": _to_int(f[2]),
            "battery_charge_current": _to_int(f[3]),
            "battery_discharge_current": _to_int(f[4]),
        }
    return None


def _match_temperature(f: list[str]) -> dict[str, Any] | None:
    # V4W3: 029 043 034 001 043 050 050 0000...  (only field 0 confirmed)
    if (
        len(f) >= 8
        and all(_RE_INT3.match(x) for x in f[:7])
        and _RE_LONGMASK.match(f[-1])
    ):
        return {"inverter_temperature": _to_int(f[0])}
    return None


# Ordered most-specific-first so each frame is claimed by exactly one matcher.
_MATCHERS = (
    _match_energy,
    _match_pv,
    _match_load,
    _match_grid,
    _match_battery,
    _match_temperature,
)


def decode_frame(text: str) -> dict[str, Any] | None:
    """Decode one telemetry text frame into named values, or None if unmatched."""
    fields = _split_frame(text)
    if not fields:
        return None
    for matcher in _MATCHERS:
        result = matcher(fields)
        if result is not None:
            # Drop keys whose conversion failed so we never publish None noise.
            return {k: v for k, v in result.items() if v is not None}
    return None


def decode_ct(ct: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Decode a ``ct`` channel array (bulk push / dump) into a flat value dict.

    Returns ``(values, unmatched_aliases)``.  `unmatched_aliases` lets the
    caller debug-log channels we couldn't fingerprint yet.
    """
    values: dict[str, Any] = {}
    unmatched: list[str] = []
    for entry in ct or []:
        co = entry.get("co")
        if not co:
            continue
        try:
            text = decode_co(co)
        except (ValueError, TypeError):
            unmatched.append(entry.get("cn", "?"))
            continue
        decoded = decode_frame(text)
        if decoded:
            values.update(decoded)
        else:
            unmatched.append(entry.get("cn", "?"))
    return values, unmatched


def derive_binary_state(values: dict[str, Any]) -> None:
    """In-place: normalize raw enum telemetry into clean booleans where known."""
    if "solar_charging_switch" in values:
        raw = str(values["solar_charging_switch"])
        values["solar_charging_switch"] = raw in SOLAR_CHARGING_SWITCH_ON
