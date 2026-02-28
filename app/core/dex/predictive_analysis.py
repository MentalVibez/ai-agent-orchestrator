"""Predictive Analysis — linear trend detection on metric snapshots.

Uses simple linear regression to project when key metrics (disk, memory, CPU)
will exceed critical thresholds, and creates DexAlerts with time-to-impact estimates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import DexAlert, EndpointMetricSnapshot

logger = logging.getLogger(__name__)

_CRITICAL_THRESHOLD = 90.0  # % — alert when projected to exceed this
_MIN_SNAPSHOTS = 3  # need at least this many points for meaningful regression


def _linear_regression(xs: List[float], ys: List[float]) -> tuple[float, float]:
    """Return (slope, intercept) of least-squares line through (x, y) pairs."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[-1] if ys else 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    slope = num / den if den != 0 else 0.0
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _hours_to_threshold(
    current_value: float,
    slope_per_hour: float,
    threshold: float = _CRITICAL_THRESHOLD,
) -> Optional[float]:
    """Return hours until the metric is projected to reach `threshold`, or None if stable/declining."""
    if slope_per_hour <= 0:
        return None
    remaining = threshold - current_value
    if remaining <= 0:
        return 0.0
    return remaining / slope_per_hour


def _format_time_to_impact(hours: float) -> str:
    if hours < 1:
        return f"{int(hours * 60)} minutes"
    elif hours < 24:
        return f"{hours:.1f} hours"
    else:
        return f"{hours / 24:.1f} days"


def _upsert_predictive_alert(
    db: Session,
    hostname: str,
    alert_name: str,
    message: str,
    predicted_time_to_impact: str,
    severity: str,
) -> DexAlert:
    """Create or update a predictive DexAlert for this hostname+alert_name combination."""
    existing = (
        db.query(DexAlert)
        .filter(
            DexAlert.hostname == hostname,
            DexAlert.alert_name == alert_name,
            DexAlert.alert_type == "predictive",
            DexAlert.status.in_(["active", "remediating"]),
        )
        .first()
    )
    if existing:
        existing.severity = severity
        existing.message = message
        existing.predicted_time_to_impact = predicted_time_to_impact
        db.commit()
        return existing

    alert = DexAlert(
        hostname=hostname,
        alert_name=alert_name,
        severity=severity,
        alert_type="predictive",
        message=message,
        predicted_time_to_impact=predicted_time_to_impact,
        status="active",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    logger.warning(
        "DEX predictive alert: hostname=%s alert=%s severity=%s tti=%s",
        hostname,
        alert_name,
        severity,
        predicted_time_to_impact,
    )
    return alert


def analyze_trends(
    db: Session,
    hostname: str,
    lookback_days: int = 7,
) -> List[Dict[str, Any]]:
    """Run trend analysis for an endpoint and return a list of trend projections.

    Also creates/updates DexAlerts for metrics trending toward critical levels.
    Returns a list of dicts describing each metric trend.
    """
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    snapshots = (
        db.query(EndpointMetricSnapshot)
        .filter(
            EndpointMetricSnapshot.hostname == hostname,
            EndpointMetricSnapshot.captured_at >= since,
        )
        .order_by(EndpointMetricSnapshot.captured_at.asc())
        .all()
    )

    if len(snapshots) < _MIN_SNAPSHOTS:
        return [
            {
                "metric": "all",
                "status": "insufficient_data",
                "message": f"Need at least {_MIN_SNAPSHOTS} snapshots; have {len(snapshots)}.",
            }
        ]

    # Build time axis in hours from earliest snapshot
    t0 = snapshots[0].captured_at
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)

    def hours_since(ts: datetime) -> float:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (ts - t0).total_seconds() / 3600

    xs = [hours_since(s.captured_at) for s in snapshots]

    metrics = {
        "disk_pct": ("DiskFull", "Disk usage", [s.disk_pct for s in snapshots]),
        "memory_pct": ("MemoryLeak", "Memory usage", [s.memory_pct for s in snapshots]),
        "cpu_pct": ("SustainedHighCPU", "CPU usage", [s.cpu_pct for s in snapshots]),
    }

    results: List[Dict[str, Any]] = []

    for field, (alert_name, label, values) in metrics.items():
        # Filter out None values
        pairs = [(x, y) for x, y in zip(xs, values) if y is not None]
        if len(pairs) < _MIN_SNAPSHOTS:
            results.append(
                {"metric": field, "status": "insufficient_data", "alert_name": alert_name}
            )
            continue

        px, py = zip(*pairs)
        slope, intercept = _linear_regression(list(px), list(py))
        current = py[-1]
        projected_24h = current + slope * 24
        projected_7d = current + slope * 168

        tti_hours = _hours_to_threshold(current, slope)
        tti_str = _format_time_to_impact(tti_hours) if tti_hours is not None else None

        trend: Dict[str, Any] = {
            "metric": field,
            "alert_name": alert_name,
            "current_value": round(current, 1),
            "slope_per_hour": round(slope, 4),
            "projected_24h": round(min(projected_24h, 100.0), 1),
            "projected_7d": round(min(projected_7d, 100.0), 1),
            "time_to_impact": tti_str,
            "status": "stable",
        }

        if tti_hours is not None and tti_hours <= 168:  # within 7 days
            severity = "critical" if tti_hours <= 24 else "warning"
            message = (
                f"{label} for {hostname} is {current:.1f}% and trending to exceed "
                f"{_CRITICAL_THRESHOLD:.0f}% in approximately {tti_str}."
            )
            _upsert_predictive_alert(
                db,
                hostname=hostname,
                alert_name=alert_name,
                message=message,
                predicted_time_to_impact=tti_str,
                severity=severity,
            )
            trend["status"] = "alert"
            trend["severity"] = severity
            trend["message"] = message
        elif slope <= 0:
            trend["status"] = "improving"
        else:
            trend["status"] = "stable_trend"

        results.append(trend)

    return results
