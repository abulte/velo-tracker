"""Application configuration — override via environment variables."""
import os

# FIXME: switch back to sonnet/opus for production
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "32000"))

# Coggan 6-zone power model. Each value is (low_inclusive, high_exclusive) as FTP fractions.
# Z6 upper bound is None (unbounded).
ZONE_BOUNDARIES: dict[str, tuple[float | None, float | None]] = {
    "z1": (None, 0.55),
    "z2": (0.55, 0.75),
    "z3": (0.75, 0.90),
    "z4": (0.90, 1.05),
    "z5": (1.05, 1.20),
    "z6": (1.20, None),
}
