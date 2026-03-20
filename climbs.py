"""Climb detection from elevation-enriched polylines."""

import math

MIN_ELEVATION_GAIN = 50    # metres
MIN_LENGTH_M = 500         # metres
MIN_AVG_GRADIENT = 0.015   # 1.5%
GAP_TOLERANCE_M = 15       # metres descent from running peak that ends a segment
START_OFFSET_M = 10        # metres above valley floor before climb is considered started


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Return distance in metres between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _smooth(values: list[float], window: int = 5) -> list[float]:
    """Apply a simple rolling mean."""
    result = []
    half = window // 2
    n = len(values)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        result.append(sum(values[lo:hi]) / (hi - lo))
    return result


def detect_climbs(polyline: list) -> list[dict]:
    """
    Detect climbs from a polyline of [lat, lon, ele] triples.

    Returns a list of dicts with keys:
        start_idx, end_idx, elevation_gain, length_m, avg_gradient,
        start_ele, end_ele, start_dist_km, end_dist_km
    """
    if not polyline:
        return []

    # Filter to points with elevation
    indexed = [
        (i, p[0], p[1], p[2])
        for i, p in enumerate(polyline)
        if len(p) > 2 and p[2] is not None
    ]
    if len(indexed) < 2:
        return []

    # Compute cumulative distances (in metres) between consecutive points
    dists = [0.0]
    for j in range(1, len(indexed)):
        _, lat1, lon1, _ = indexed[j - 1]
        _, lat2, lon2, _ = indexed[j]
        dists.append(dists[-1] + _haversine(lat1, lon1, lat2, lon2))

    eles = [pt[3] for pt in indexed]
    smoothed = _smooth(eles)

    # Walk forward accumulating climbs
    climbs = []
    n = len(indexed)
    i = 0
    while i < n - 1:
        # Look for start of a climb
        if smoothed[i + 1] <= smoothed[i]:
            i += 1
            continue

        # We have a rising segment — track the climb.
        # End the climb when elevation drops more than GAP_TOLERANCE_M below the running peak.
        climb_start = i
        peak_i = i
        peak_ele = smoothed[i]

        j = i + 1
        while j < n:
            if smoothed[j] > peak_ele:
                peak_ele = smoothed[j]
                peak_i = j
            elif peak_ele - smoothed[j] > GAP_TOLERANCE_M:
                break
            j += 1

        end_i = peak_i

        # Find the true climb start: locate the elevation minimum in the segment,
        # then advance forward until elevation rises more than GAP_TOLERANCE_M
        # above that minimum — that's the foot of the actual climb.
        min_i = min(range(climb_start, end_i + 1), key=lambda k: smoothed[k])
        s = min_i
        base_ele = smoothed[min_i]
        while s < end_i and smoothed[s] <= base_ele + START_OFFSET_M:
            s += 1
        climb_start = s

        length_m = dists[end_i] - dists[climb_start]
        ele_gain = smoothed[end_i] - smoothed[climb_start]
        avg_grad = ele_gain / length_m if length_m > 0 else 0

        if (ele_gain >= MIN_ELEVATION_GAIN
                and length_m >= MIN_LENGTH_M
                and avg_grad >= MIN_AVG_GRADIENT):
            climbs.append(dict(
                start_idx=indexed[climb_start][0],
                end_idx=indexed[end_i][0],
                elevation_gain=round(ele_gain, 1),
                length_m=round(length_m),
                avg_gradient=round(avg_grad * 100, 1),
                start_ele=round(smoothed[climb_start], 1),
                end_ele=round(smoothed[end_i], 1),
                start_dist_km=round(dists[climb_start] / 1000, 2),
                end_dist_km=round(dists[end_i] / 1000, 2),
            ))

        i = end_i + 1 if end_i > i else i + 1

    return climbs
