"""Climb detection from elevation-enriched polylines.

Algorithm
---------
1. Compute cumulative distances between polyline points (haversine).
2. Simplify the elevation profile with iterative Ramer-Douglas-Peucker (RDP),
   using the elevation residual (vertical deviation) as the distance metric.
   This simultaneously removes GPS noise and produces clean segment boundaries
   without the smoothing-window heuristics needed by simpler approaches.
3. Walk the simplified segments: start a climb on any ascending segment, end it
   when the descent from the running peak exceeds MAX_GAP_FRACTION of the total
   gain so far.  The climb is recorded at the highest point reached.
4. Filter candidates by MIN_GRADE, MIN_LENGTH_M, and MIN_GAIN_M.

Threshold rationale
-------------------
MIN_GRADE     2 %    Industry standard is 3 %, but this user's terrain is
                     relatively shallow; 2 % catches real climbs without
                     producing false positives on flat rides.
MIN_GAIN_M    30 m   Equivalent to a score of 3 000 (length × grade × 100),
                     the lower end of GPSLogger / Strava categorisation.
MIN_LENGTH_M  500 m  Filters out short punchy ramps that aren't sustained climbs.
MAX_GAP_FRAC  30 %   How far below the running peak (as a fraction of total
                     gain) the route can drop before the climb is considered
                     ended.  50 % is the GPSLogger default; 30 % gives better
                     separation on routes with back-to-back climbs.
RDP_EPSILON   1.5 m  Points deviating less than 1.5 m from the simplified line
                     are discarded — covers GPS quantisation and sensor noise.

References
----------
- alex-hhh AL2-Climb-Analysis — RDP + FIETS scoring (ActivityLog2)
- GPSLogger climb detection — 4-rule gate + descent-fraction rule
- Strava climb categorisation — score = length × grade ≥ 8 000, grade ≥ 3 %
"""

import math

MIN_GRADE        = 0.02   # minimum average gradient (fraction, not %)
MIN_GAIN_M       = 30     # metres — minimum net elevation gain
MIN_LENGTH_M     = 500    # metres — minimum climb length
MAX_GAP_FRACTION = 0.3    # maximum descent from peak as a fraction of total gain
RDP_EPSILON      = 1.5    # metres — elevation residual threshold for RDP


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _rdp(profile, epsilon):
    """Iterative Ramer-Douglas-Peucker simplification on an elevation profile.

    Unlike the standard geometric RDP, the distance metric here is the
    *elevation residual* — the vertical deviation of a point from the line
    between two endpoints at the same cumulative distance.  This means epsilon
    is directly in metres of elevation, making it easy to tune.

    Args:
        profile: list of (dist_m, ele_m, original_polyline_idx) tuples.
        epsilon: maximum elevation residual to discard (metres).

    Returns:
        Simplified list with the same tuple format, preserving first/last points.
    """
    n = len(profile)
    if n < 3:
        return list(profile)

    keep = {0, n - 1}
    stack = [(0, n - 1)]

    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue

        d1, e1, _ = profile[start]
        d2, e2, _ = profile[end]
        dspan = d2 - d1

        max_res = 0.0
        max_k = start + 1

        for k in range(start + 1, end):
            dk, ek, _ = profile[k]
            if dspan == 0:
                res = abs(ek - e1)
            else:
                t = (dk - d1) / dspan
                res = abs(ek - (e1 + t * (e2 - e1)))
            if res > max_res:
                max_res = res
                max_k = k

        if max_res > epsilon:
            keep.add(max_k)
            stack.append((start, max_k))
            stack.append((max_k, end))

    return [profile[k] for k in sorted(keep)]


def detect_climbs(polyline: list) -> list[dict]:
    """Detect climbs from a polyline of [lat, lon, ele] triples.

    Points without elevation (len < 3 or ele is None) are silently skipped.
    Returns an empty list if there is no elevation data.

    Returns:
        List of dicts, one per climb, with keys:
            start_idx, end_idx     — indices into the original polyline (for
                                     chart highlighting in the frontend)
            elevation_gain         — net gain in metres
            length_m               — horizontal length in metres
            avg_gradient           — average gradient in %
            start_ele, end_ele     — elevations at start/peak in metres
            start_dist_km,
            end_dist_km            — cumulative distances from ride start in km
    """
    if not polyline:
        return []

    # Keep only points that carry valid elevation data
    indexed = [
        (i, p[0], p[1], p[2])
        for i, p in enumerate(polyline)
        if len(p) > 2 and p[2] is not None
    ]
    if len(indexed) < 2:
        return []

    # Cumulative distances along the track (metres)
    dists = [0.0]
    for j in range(1, len(indexed)):
        _, lat1, lon1, _ = indexed[j - 1]
        _, lat2, lon2, _ = indexed[j]
        dists.append(dists[-1] + _haversine(lat1, lon1, lat2, lon2))

    # Build and simplify the elevation profile
    profile = [(dists[k], indexed[k][3], indexed[k][0]) for k in range(len(indexed))]
    simplified = _rdp(profile, RDP_EPSILON)
    if len(simplified) < 2:
        return []

    # Convert RDP breakpoints into linear segments.
    # Each segment is a tuple: (d_start, d_end, e_start, e_end,
    #                           idx_start, idx_end, length_m, grade)
    segs = []
    for j in range(len(simplified) - 1):
        d1, e1, i1 = simplified[j]
        d2, e2, i2 = simplified[j + 1]
        length = d2 - d1
        if length > 0:
            segs.append((d1, d2, e1, e2, i1, i2, length, (e2 - e1) / length))

    if not segs:
        return []

    climbs = []
    ns = len(segs)
    i = 0

    while i < ns:
        d1, d2, e1, e2, i1, i2, seg_len, grade = segs[i]

        if grade <= 0:
            i += 1
            continue

        # An ascending segment triggers a new candidate climb
        start_d, start_e, start_idx = d1, e1, i1
        peak_d, peak_e, peak_idx    = d1, e1, i1

        j = i
        while j < ns:
            _sd, ed, _se, ee, _si, ei, _slen, _sgrade = segs[j]

            # Keep tracking the highest elevation reached
            if ee > peak_e:
                peak_e, peak_d, peak_idx = ee, ed, ei

            # End the climb if we've dropped more than MAX_GAP_FRACTION of the
            # total gain below the running peak
            total_gain = peak_e - start_e
            if total_gain > 0 and (peak_e - ee) > total_gain * MAX_GAP_FRACTION:
                break

            j += 1

        # Record the climb ending at the highest point reached
        end_d, end_e, end_idx = peak_d, peak_e, peak_idx
        length_m  = end_d - start_d
        ele_gain  = end_e - start_e
        avg_grade = ele_gain / length_m if length_m > 0 else 0

        if ele_gain >= MIN_GAIN_M and length_m >= MIN_LENGTH_M and avg_grade >= MIN_GRADE:
            climbs.append(dict(
                start_idx=start_idx,
                end_idx=end_idx,
                elevation_gain=round(ele_gain, 1),
                length_m=round(length_m),
                avg_gradient=round(avg_grade * 100, 1),
                start_ele=round(start_e, 1),
                end_ele=round(end_e, 1),
                start_dist_km=round(start_d / 1000, 2),
                end_dist_km=round(end_d / 1000, 2),
            ))

        # Resume search from the first segment that starts at or after the peak
        i = next((k for k in range(i + 1, ns) if segs[k][0] >= end_d), ns)

    return climbs
