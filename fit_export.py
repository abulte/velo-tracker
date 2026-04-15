"""Generate Garmin-compatible .fit workout files from TrainingSession steps."""
import datetime
import struct

from config import ZONE_BOUNDARIES

WARMUP, ACTIVE, REST, COOLDOWN = 2, 0, 1, 3

_INTENSITY_MAP: dict[str, int] = {
    "warmup": WARMUP,
    "cooldown": COOLDOWN,
    "rest": REST,
    "recovery": REST,
}

_FIT_EPOCH = datetime.datetime(1989, 12, 31, tzinfo=datetime.timezone.utc)


def _fit_crc(data: bytes, crc: int = 0) -> int:
    crc_table = [
        0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
    ]
    for byte in data:
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ crc_table[byte & 0xF]
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ crc_table[(byte >> 4) & 0xF]
    return crc


def _str16(s: str) -> bytes:
    b = s.encode("utf-8")[:15]
    return b + b"\x00" * (16 - len(b))


def _zone_watts(zone: str, ftp: int) -> tuple[int, int]:
    """Return (low_w, high_w) for a power zone given FTP in watts."""
    lo, hi = ZONE_BOUNDARIES.get(zone, (0.55, 0.75))
    low_w = int(lo * ftp) if lo is not None else 1  # 0 maps to 1000 raw which is a sentinel; use 1
    high_w = int(hi * ftp) if hi is not None else int(1.5 * ftp)
    return low_w, high_w


def _flatten(steps: list[dict]) -> list[dict]:
    """Unroll 'set' (repeat) steps into a flat list of individual steps."""
    flat: list[dict] = []
    for step in steps:
        if step.get("type") == "set":
            inner = step.get("steps", [])
            for _ in range(int(step.get("repeat", 1))):
                flat.extend(_flatten(inner))
        else:
            flat.append(step)
    return flat


def session_to_fit(title: str, steps: list[dict], ftp: int) -> bytes:
    """
    Convert a session's step list to a Garmin-compatible .fit workout file.

    steps: list of step dicts as stored in TrainingSession.steps
           Each step has: type, duration_sec, zone, cadence?, description?
           Set steps have: type='set', repeat, steps=[...]
    ftp:   athlete FTP in watts (required for zone → watt conversion)

    Returns raw .fit file bytes, compatible with Garmin USB and intervals.icu import.
    """
    flat = _flatten(steps)
    ts = int((datetime.datetime.now(datetime.timezone.utc) - _FIT_EPOCH).total_seconds())

    body = bytearray()

    # Local message 0: file_id (mesg 0)
    body += struct.pack("<BBBHB", 0x40, 0, 0, 0, 3)
    body += struct.pack("<BBB", 4, 4, 0x86)   # time_created uint32
    body += struct.pack("<BBB", 1, 2, 0x84)   # manufacturer uint16
    body += struct.pack("<BBB", 0, 1, 0x00)   # type uint8
    body += struct.pack("<B", 0x00)
    body += struct.pack("<I", ts)
    body += struct.pack("<H", 1)               # manufacturer = Garmin
    body += struct.pack("<B", 5)               # type = workout

    # Local message 1: workout (mesg 26)
    body += struct.pack("<BBBHB", 0x41, 0, 0, 26, 3)
    body += struct.pack("<BBB", 4,  1, 0x00)  # sport
    body += struct.pack("<BBB", 6,  2, 0x84)  # num_valid_steps
    body += struct.pack("<BBB", 8, 16, 0x07)  # wkt_name string[16]
    body += struct.pack("<B", 0x01)
    body += struct.pack("<B", 2)               # sport = cycling
    body += struct.pack("<H", len(flat))
    body += _str16(title)

    # Local message 2: workout_step (mesg 27) — field numbers must match FIT SDK exactly
    body += struct.pack("<BBBHB", 0x42, 0, 0, 27, 9)
    body += struct.pack("<BBB", 254,  2, 0x84)  # message_index  uint16
    body += struct.pack("<BBB",   0, 16, 0x07)  # wkt_step_name  string[16]
    body += struct.pack("<BBB",   1,  1, 0x00)  # duration_type  uint8
    body += struct.pack("<BBB",   2,  4, 0x86)  # duration_value uint32 (milliseconds)
    body += struct.pack("<BBB",   3,  1, 0x00)  # target_type    uint8
    body += struct.pack("<BBB",   4,  4, 0x86)  # target_value   uint32
    body += struct.pack("<BBB",   5,  4, 0x86)  # custom_target_value_low  uint32
    body += struct.pack("<BBB",   6,  4, 0x86)  # custom_target_value_high uint32
    body += struct.pack("<BBB",   7,  1, 0x00)  # intensity      uint8

    for idx, step in enumerate(flat):
        zone = str(step.get("zone", "z2"))
        low_w, high_w = _zone_watts(zone, ftp)
        dur_s = int(step.get("duration_sec", 0))
        intensity = _INTENSITY_MAP.get(str(step.get("type", "")).lower(), ACTIVE)
        name = str(step.get("description") or step.get("type") or "step")

        body += struct.pack("<B", 0x02)
        body += struct.pack("<H", idx)
        body += _str16(name)
        body += struct.pack("<B", 0)             # duration_type = TIME
        body += struct.pack("<I", dur_s * 1000)  # duration in milliseconds
        body += struct.pack("<B", 4)             # target_type = POWER
        body += struct.pack("<I", 0)             # target_value = 0 (use custom range)
        body += struct.pack("<I", low_w + 1000)  # custom_target_value_low  (+1000 offset)
        body += struct.pack("<I", high_w + 1000) # custom_target_value_high (+1000 offset)
        body += struct.pack("<B", intensity)

    data_size = len(body)
    hdr = struct.pack("<BBHI4s", 14, 0x10, 0x083C, data_size, b".FIT")
    hdr += struct.pack("<H", _fit_crc(hdr))
    full = bytes(hdr) + bytes(body)
    full += struct.pack("<H", _fit_crc(full))

    return full
