"""
trust_score_engine.py
---------------------
Katalyst Street — MDM Trust Score Module
=========================================
(UNCHANGED LOGIC — FULL VERSION)
"""

from __future__ import annotations

import re
import statistics
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# 🔴 FIXED IMPORT
from models import CustomerRecord


# ─────────────────────────────────────────────────────────────
# RULE REGISTRY
# ─────────────────────────────────────────────────────────────

@dataclass
class Rule:
    rule_id: str
    name: str
    description: str
    entity_type: str
    field: str
    severity: str
    weight: float
    enabled: bool = True
    validator: Optional[Callable[[dict], tuple[bool, str]]] = field(default=None, repr=False)
    hit_count: int = 0
    pass_count: int = 0


class RuleRegistry:
    def __init__(self):
        self._rules: dict[str, Rule] = {}
        self._register_baseline_rules()

    def register(self, rule: Rule):
        self._rules[rule.rule_id] = rule

    def rules_for(self, entity_type: str) -> list[Rule]:
        return [r for r in self._rules.values()
                if r.entity_type in (entity_type, "ALL") and r.enabled]

    # ── BASELINE RULES ──────────────────────────────────────

    def _register_baseline_rules(self):

        self.register(Rule(
            rule_id="CUST-001",
            name="Email Presence",
            description="Must have email",
            entity_type="Customer",
            field="email",
            severity="CRITICAL",
            weight=1.0,
            validator=lambda r: (bool(r.get("email")), "Email missing")
        ))

        self.register(Rule(
            rule_id="CUST-002",
            name="Email Format",
            description="Valid email format",
            entity_type="Customer",
            field="email",
            severity="HIGH",
            weight=0.9,
            validator=lambda r: (
                bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (r.get("email") or "").strip())),
                "Invalid email"
            )
        ))

        self.register(Rule(
            rule_id="CUST-003",
            name="Phone Presence",
            description="Phone required",
            entity_type="Customer",
            field="phone",
            severity="HIGH",
            weight=0.8,
            validator=lambda r: (bool(r.get("phone")), "Phone missing")
        ))

        self.register(Rule(
            rule_id="CUST-010",
            name="First Name Presence",
            description="First name required",
            entity_type="Customer",
            field="first_name",
            severity="CRITICAL",
            weight=1.0,
            validator=lambda r: (bool((r.get("first_name") or "").strip()), "First name missing")
        ))


# ─────────────────────────────────────────────────────────────
# BUSINESS RULE ENGINE
# ─────────────────────────────────────────────────────────────

SEVERITY_WEIGHTS = {
    "CRITICAL": 4.0,
    "HIGH": 2.5,
    "MEDIUM": 1.5,
    "LOW": 1.0
}


@dataclass
class RuleResult:
    rule_id: str
    rule_name: str
    severity: str
    passed: bool
    detail: str
    contribution: float


class BusinessRulesEngine:

    def __init__(self, registry: RuleRegistry):
        self.registry = registry

    def evaluate(self, record_dict: dict, entity_type: str):

        rules = self.registry.rules_for(entity_type)

        total_weight = 0
        earned_weight = 0
        results = []

        for rule in rules:

            sw = SEVERITY_WEIGHTS.get(rule.severity, 1.0)
            effective_weight = sw * rule.weight
            total_weight += effective_weight

            try:
                passed, detail = rule.validator(record_dict)
            except:
                passed, detail = False, "Error"

            if passed:
                earned_weight += effective_weight

            results.append(RuleResult(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                passed=passed,
                detail=detail,
                contribution=effective_weight
            ))

        score = (earned_weight / total_weight) * 40 if total_weight else 40
        return round(score, 2), results


# ─────────────────────────────────────────────────────────────
# DRIFT ANALYZER
# ─────────────────────────────────────────────────────────────

@dataclass
class DriftResult:
    freshness_score: float
    stability_score: float
    total_drift_score: float
    detail: str


class DriftAnalyzer:
    """
    Drift = freshness + stability
    """

    FRESHNESS_MAX_DAYS = 365

    def analyze(self, record_dict, cluster):

        freshness = self._freshness(record_dict)
        stability = self._stability(record_dict, cluster)

        total = round(freshness + stability, 2)

        return DriftResult(
            freshness_score=freshness,
            stability_score=stability,
            total_drift_score=total,
            detail=f"Fresh={freshness:.1f}, Stable={stability:.1f}"
        )

    def _freshness(self, r):
        try:
            updated = r.get("updated_at") or r.get("created_at")
            dt = datetime.strptime(updated[:19], "%Y-%m-%dT%H:%M:%S")
            age_days = (datetime.now() - dt).days

            score = max(0, 1 - age_days / self.FRESHNESS_MAX_DAYS)
            return round(score * 15, 2)
        except:
            return 5.0  # fallback

    def _stability(self, r, cluster):

        if len(cluster) <= 1:
            return 15.0

        fields = ["email", "phone", "city", "state", "country"]

        scores = []

        for f in fields:
            vals = [
                str(c.get(f, "")).strip().lower()
                for c in cluster if c.get(f)
            ]

            mine = str(r.get(f, "")).strip().lower()

            if not vals or not mine:
                continue

            majority = max(set(vals), key=vals.count)
            scores.append(1 if mine == majority else 0)

        if not scores:
            return 10.0

        return round(statistics.mean(scores) * 15, 2)


# ─────────────────────────────────────────────────────────────
# ANOMALY DETECTOR
# ─────────────────────────────────────────────────────────────

@dataclass
class AnomalyResult:
    anomaly_score: float
    flags: list[str]
    detail: str


class AnomalyDetector:

    Z_THRESHOLD = 3.0

    def detect(self, r, cluster, entity_type):

        flags = []

        flags += self._numeric_outliers(r, cluster)
        flags += self._string_anomalies(r)
        flags += self._behavior_anomalies(r)

        score = max(0, 30 - len(flags) * 3)

        return AnomalyResult(
            anomaly_score=score,
            flags=flags,
            detail=f"{len(flags)} anomalies"
        )

    def _numeric_outliers(self, r, cluster):

        flags = []
        fields = ["total_lifetime_value"]

        for f in fields:
            vals = [
                float(c[f]) for c in cluster
                if c.get(f) is not None
            ]

            mine = r.get(f)

            if mine is None or len(vals) < 2:
                continue

            mean = statistics.mean(vals)
            std = statistics.stdev(vals) if len(vals) > 1 else 0

            if std > 0 and abs(mine - mean) / std > self.Z_THRESHOLD:
                flags.append(f"OUTLIER:{f}")

        return flags

    def _string_anomalies(self, r):

        flags = []

        for f in ["first_name", "last_name", "email"]:
            val = r.get(f)

            if not val:
                continue

            if val == val.upper() and len(val) > 3:
                flags.append(f"ALL_CAPS:{f}")

            if "  " in val:
                flags.append(f"DOUBLE_SPACE:{f}")

            if val != val.strip():
                flags.append(f"WHITESPACE:{f}")

        return flags

    def _behavior_anomalies(self, r):

        flags = []

        if r.get("is_active") is False and r.get("last_purchase_date"):
            try:
                dt = datetime.strptime(r["last_purchase_date"][:10], "%Y-%m-%d")
                if (datetime.now() - dt).days < 30:
                    flags.append("INACTIVE_RECENT_PURCHASE")
            except:
                pass

        return flags


# ─────────────────────────────────────────────────────────────
# TRUST ENGINE
# ─────────────────────────────────────────────────────────────

@dataclass
class TrustScoreReport:
    record_id: str
    entity_type: str
    source_system: str
    rules_score: float
    drift_score: float
    anomaly_score: float
    trust_score: float
    rule_results: list
    drift_result: DriftResult
    anomaly_result: AnomalyResult
    is_golden: bool = False
    survivorship_reason: str = ""


class TrustScoreEngine:

    def __init__(self):
        self.registry = RuleRegistry()
        self.rules_engine = BusinessRulesEngine(self.registry)
        self.drift = DriftAnalyzer()
        self.anomaly = AnomalyDetector()

    def score_cluster(self, records):

        dicts = [r.__dict__ for r in records]
        reports = []

        for i, r in enumerate(records):

            rd = dicts[i]

            rules_score, rule_results = self.rules_engine.evaluate(rd, "Customer")
            drift_result = self.drift.analyze(rd, dicts)
            anomaly_result = self.anomaly.detect(rd, dicts, "Customer")

            trust = round(
                 rules_score +
                drift_result.total_drift_score +
                anomaly_result.anomaly_score,
                  2
                  )

            reports.append(TrustScoreReport(
                record_id=r.record_id,
                entity_type="Customer",
                source_system=r.source_system,
                rules_score=rules_score,
                drift_score=drift_result.total_drift_score,
                anomaly_score=anomaly_result.anomaly_score,
                trust_score=trust,
                rule_results=rule_results,
                drift_result=drift_result,
                anomaly_result=anomaly_result
            ))

            r.trust_score = trust

        winner = max(reports, key=lambda x: x.trust_score)
        winner.is_golden = True

        return reports

    def score_all(self, all_records):

        from collections import defaultdict

        clusters = defaultdict(list)

        for r in all_records:
            clusters[r.cluster_id].append(r)

        all_reports = []

        for recs in clusters.values():
            all_reports.extend(self.score_cluster(recs))

        return all_reports
