"""DEX Score Engine — calculates composite health score (0–100) from metric snapshots.

Score = weighted average of 4 components:
  - Device Health   (40%): CPU, memory, disk usage
  - Network Quality (30%): latency, packet loss, DNS
  - App Performance (20%): services down, log error rate
  - Remediation     (10%): % of recent alerts auto-resolved
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models import DexAlert, DexScoreRecord, EndpointMetricSnapshot

logger = logging.getLogger(__name__)

# Score component weights (must sum to 1.0)
_WEIGHTS = {
    "device_health": 0.40,
    "network": 0.30,
    "app_performance": 0.20,
    "remediation": 0.10,
}


@dataclass
class ScoreComponents:
    device_health: float = 100.0
    network: float = 100.0
    app_performance: float = 100.0
    remediation: float = 100.0
    deductions: List[str] = field(default_factory=list)

    @property
    def composite(self) -> float:
        raw = (
            self.device_health * _WEIGHTS["device_health"]
            + self.network * _WEIGHTS["network"]
            + self.app_performance * _WEIGHTS["app_performance"]
            + self.remediation * _WEIGHTS["remediation"]
        )
        return max(0.0, min(100.0, round(raw, 1)))


def _score_device_health(snapshot: EndpointMetricSnapshot) -> tuple[float, List[str]]:
    """Return (score 0–100, list of deduction reasons) for device health."""
    score = 100.0
    reasons: List[str] = []

    cpu = snapshot.cpu_pct
    if cpu is not None:
        if cpu > 95:
            score -= 40
            reasons.append(f"CPU critical: {cpu:.1f}%")
        elif cpu > 80:
            score -= 20
            reasons.append(f"CPU high: {cpu:.1f}%")

    mem = snapshot.memory_pct
    if mem is not None:
        if mem > 95:
            score -= 35
            reasons.append(f"Memory critical: {mem:.1f}%")
        elif mem > 85:
            score -= 15
            reasons.append(f"Memory high: {mem:.1f}%")

    disk = snapshot.disk_pct
    if disk is not None:
        if disk > 95:
            score -= 40
            reasons.append(f"Disk critical: {disk:.1f}%")
        elif disk > 85:
            score -= 20
            reasons.append(f"Disk high: {disk:.1f}%")

    return max(0.0, score), reasons


def _score_network(snapshot: EndpointMetricSnapshot) -> tuple[float, List[str]]:
    """Return (score 0–100, deductions) for network quality."""
    score = 100.0
    reasons: List[str] = []

    latency = snapshot.network_latency_ms
    if latency is not None:
        if latency > 500:
            score -= 30
            reasons.append(f"Latency critical: {latency:.0f}ms")
        elif latency > 100:
            score -= 10
            reasons.append(f"Latency elevated: {latency:.0f}ms")

    loss = snapshot.packet_loss_pct
    if loss is not None:
        if loss > 5:
            score -= 40
            reasons.append(f"Packet loss critical: {loss:.1f}%")
        elif loss > 1:
            score -= 20
            reasons.append(f"Packet loss detected: {loss:.1f}%")

    return max(0.0, score), reasons


def _score_app_performance(snapshot: EndpointMetricSnapshot) -> tuple[float, List[str]]:
    """Return (score 0–100, deductions) for app and service performance."""
    score = 100.0
    reasons: List[str] = []

    services_down: List[str] = snapshot.services_down or []
    for svc in services_down:
        score -= 15
        reasons.append(f"Service down: {svc}")

    errors = snapshot.log_error_count or 0
    if errors > 50:
        score -= 30
        reasons.append(f"High log error count: {errors}")
    elif errors > 10:
        score -= 10
        reasons.append(f"Elevated log errors: {errors}")

    return max(0.0, score), reasons


def _score_remediation(db: Session, hostname: str, lookback_days: int = 7) -> tuple[float, List[str]]:
    """Return (score 0–100) based on auto-resolution rate of recent alerts."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    alerts = (
        db.query(DexAlert)
        .filter(DexAlert.hostname == hostname, DexAlert.created_at >= since)
        .all()
    )
    if not alerts:
        return 100.0, []  # no alerts = perfect remediation score

    resolved = sum(1 for a in alerts if a.status == "resolved")
    rate = resolved / len(alerts)
    score = round(rate * 100, 1)
    reasons = []
    if rate < 0.5:
        reasons.append(f"Low auto-resolution rate: {rate*100:.0f}% over {lookback_days}d")
    return score, reasons


def calculate_score(
    db: Session,
    hostname: str,
    snapshot: EndpointMetricSnapshot,
) -> DexScoreRecord:
    """Calculate a DEX score from the latest snapshot and persist it to the DB."""
    all_deductions: List[str] = []

    dh, dh_reasons = _score_device_health(snapshot)
    nq, nq_reasons = _score_network(snapshot)
    ap, ap_reasons = _score_app_performance(snapshot)
    rem, rem_reasons = _score_remediation(db, hostname)
    all_deductions = dh_reasons + nq_reasons + ap_reasons + rem_reasons

    components = ScoreComponents(
        device_health=dh,
        network=nq,
        app_performance=ap,
        remediation=rem,
        deductions=all_deductions,
    )

    record = DexScoreRecord(
        hostname=hostname,
        score=components.composite,
        device_health_score=dh,
        network_score=nq,
        app_performance_score=ap,
        remediation_score=rem,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info(
        "DEX score: hostname=%s score=%.1f (device=%.1f net=%.1f app=%.1f rem=%.1f)",
        hostname,
        components.composite,
        dh,
        nq,
        ap,
        rem,
    )
    return record


def get_latest_score(db: Session, hostname: str) -> Optional[DexScoreRecord]:
    """Return the most recent DexScoreRecord for an endpoint, or None."""
    return (
        db.query(DexScoreRecord)
        .filter(DexScoreRecord.hostname == hostname)
        .order_by(DexScoreRecord.scored_at.desc(), DexScoreRecord.id.desc())
        .first()
    )


def get_score_history(
    db: Session, hostname: str, limit: int = 96
) -> List[DexScoreRecord]:
    """Return recent score records (default: last 96 readings = ~24h at 15-min intervals)."""
    return (
        db.query(DexScoreRecord)
        .filter(DexScoreRecord.hostname == hostname)
        .order_by(DexScoreRecord.scored_at.desc())
        .limit(limit)
        .all()
    )


def evaluate_thresholds(
    db: Session,
    hostname: str,
    score_record: DexScoreRecord,
    alert_threshold: int = 60,
    critical_threshold: int = 40,
) -> Optional[DexAlert]:
    """Create a DexAlert if the composite score falls below configured thresholds.

    Returns the newly created alert, or None if no threshold was breached.
    """

    score = score_record.score
    if score > alert_threshold:
        return None

    severity = "critical" if score <= critical_threshold else "warning"
    alert_name = "LowDexScore"
    message = (
        f"DEX score for {hostname} is {score:.1f} "
        f"(threshold: {critical_threshold if severity == 'critical' else alert_threshold})"
    )

    # Check if an active alert already exists — avoid duplicate creation
    existing = (
        db.query(DexAlert)
        .filter(
            DexAlert.hostname == hostname,
            DexAlert.alert_name == alert_name,
            DexAlert.status.in_(["active", "remediating"]),
        )
        .first()
    )
    if existing:
        # Update severity if it escalated
        if severity == "critical" and existing.severity != "critical":
            existing.severity = "critical"
            existing.message = message
            db.commit()
        return existing

    alert = DexAlert(
        hostname=hostname,
        alert_name=alert_name,
        severity=severity,
        alert_type="threshold",
        message=message,
        status="active",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    logger.warning(
        "DEX alert created: hostname=%s severity=%s score=%.1f", hostname, severity, score
    )
    return alert
