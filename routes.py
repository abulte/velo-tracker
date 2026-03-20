"""Route management: geohash-based similarity matching."""

import geohash2
from sqlmodel import Session, select

GEOHASH_PRECISION = 6  # ~600m × 600m cells
SIMILARITY_THRESHOLD = 0.7


def polyline_to_geohashes(polyline: list) -> set:
    return {geohash2.encode(lat, lon, GEOHASH_PRECISION) for lat, lon in polyline}


def similarity(poly_a: list, poly_b: list) -> float:
    """Overlap similarity: intersection / max(|A|, |B|).
    Tolerates small GPS deviations while penalising large size differences."""
    a = polyline_to_geohashes(poly_a)
    b = polyline_to_geohashes(poly_b)
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a), len(b))


def match_activity_to_routes(session: Session, activity) -> "object | None":
    """Return the best-matching Route for `activity`, or None."""
    from models import Activity, Route

    if not activity.polyline:
        return None

    routes = session.exec(select(Route)).all()
    if not routes:
        return None

    best_route = None
    best_score = 0.0

    for route in routes:
        ref = session.exec(
            select(Activity).where(Activity.garmin_id == route.reference_activity_id)
        ).first()
        if not ref or not ref.polyline:
            continue
        score = similarity(activity.polyline, ref.polyline)
        if score > best_score:
            best_score = score
            best_route = route

    if best_score >= SIMILARITY_THRESHOLD:
        return best_route
    return None


def assign_route_to_all(session: Session, route) -> int:
    """Assign `route` to all activities whose polyline matches its reference. Returns count."""
    from models import Activity

    ref = session.exec(
        select(Activity).where(Activity.garmin_id == route.reference_activity_id)
    ).first()
    if not ref or not ref.polyline:
        return 0

    activities = session.exec(
        select(Activity).where(Activity.polyline.isnot(None))
    ).all()

    count = 0
    for activity in activities:
        if not activity.polyline:
            continue
        score = similarity(activity.polyline, ref.polyline)
        if score >= SIMILARITY_THRESHOLD:
            activity.route_id = route.id
            session.add(activity)
            count += 1

    return count
