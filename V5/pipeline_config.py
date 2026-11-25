"""Validated persisted overrides for parameters used by the V5 trust pipeline."""

import json
import math
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parent / "hyperparams.json"

PARAMETER_BOUNDS = {
    "W_ISO": (0.0, 1.0),
    "W_IQR": (0.0, 1.0),
    "W_MISSING": (0.0, 1.0),
    "W_DUPLICATE": (0.0, 1.0),
    "W_KNN": (0.0, 1.0),
    "W_ARIMA": (0.0, 1.0),
    "ARIMA_SIGMA_K": (1.0, 6.0),
    "ARIMA_MIN_COL_FLAGS": (1.0, 10.0),
    "ARIMA_MIN_TRAIN_POINTS": (2.0, 20.0),
    "KNN_K": (1.0, 30.0),
    "KNN_PERCENTILE": (0.90, 0.999),
    "ISO_N_ESTIMATORS": (10.0, 500.0),
    "ISO_DECISION_THRESHOLD": (-1.0, 1.0),
    "IQR_MULTIPLIER": (1.0, 15.0),
    "WEIGHT_MAHAL": (0.0, 1.0),
    "WEIGHT_WELCH": (0.0, 1.0),
    "WEIGHT_PSI": (0.0, 1.0),
    "FRESHNESS_TAU": (1.0, 30.0),
    "WEIGHT_ANOMALY_HEALTH": (0.0, 1.0),
    "WEIGHT_DRIFT_HEALTH": (0.0, 1.0),
    "WEIGHT_BUSINESS_HEALTH": (0.0, 1.0),
    "WEIGHT_FRESHNESS_HEALTH": (0.0, 1.0),
    "BR_CREDIT_SCORE_MIN": (100.0, 600.0),
    "BR_CREDIT_SCORE_MAX": (700.0, 999.0),
    "BR_CREDIT_UTIL_MAX": (80.0, 200.0),
    "BR_EMPLOYEE_COUNT_MAX": (100.0, 50000.0),
    "BR_LOW_CREDIT_SCORE": (300.0, 600.0),
    "BR_MONTHS_LAST_PAYMENT_MAX": (12.0, 360.0),
    "BR_BANKRUPTCY_CREDIT_SCORE_MIN": (500.0, 850.0),
    "MAX_POSSIBLE_FLAGS": (10.0, 50.0),
}

DEFAULT_PARAMS = {
    "W_ISO": 0.20,
    "W_IQR": 0.20,
    "W_MISSING": 0.10,
    "W_DUPLICATE": 0.05,
    "W_KNN": 0.15,
    "W_ARIMA": 0.30,
    "ARIMA_SIGMA_K": 3.0,
    "ARIMA_MIN_COL_FLAGS": 2,
    "ARIMA_MIN_TRAIN_POINTS": 5,
    "KNN_K": 5,
    "KNN_PERCENTILE": 0.99,
    "ISO_N_ESTIMATORS": 64,
    "ISO_DECISION_THRESHOLD": 0,
    "IQR_MULTIPLIER": 5,
    "WEIGHT_MAHAL": 0.70,
    "WEIGHT_WELCH": 0.10,
    "WEIGHT_PSI": 0.20,
    "FRESHNESS_TAU": 5.0,
    "WEIGHT_ANOMALY_HEALTH": 0.40,
    "WEIGHT_DRIFT_HEALTH": 0.25,
    "WEIGHT_BUSINESS_HEALTH": 0.20,
    "WEIGHT_FRESHNESS_HEALTH": 0.15,
    "BR_CREDIT_SCORE_MIN": 300,
    "BR_CREDIT_SCORE_MAX": 900,
    "BR_CREDIT_UTIL_MAX": 100,
    "BR_EMPLOYEE_COUNT_MAX": 5000,
    "BR_LOW_CREDIT_SCORE": 450,
    "BR_MONTHS_LAST_PAYMENT_MAX": 120,
    "BR_BANKRUPTCY_CREDIT_SCORE_MIN": 750,
    "MAX_POSSIBLE_FLAGS": 22,
}


def validate_params(params: Any) -> dict[str, int | float]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")

    unknown = set(params) - PARAMETER_BOUNDS.keys()
    if unknown:
        raise ValueError(f"Unsupported parameter(s): {', '.join(sorted(unknown))}")

    validated: dict[str, int | float] = {}
    for name, value in params.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        number = float(value)
        minimum, maximum = PARAMETER_BOUNDS[name]
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        if name in {"ARIMA_MIN_COL_FLAGS", "ARIMA_MIN_TRAIN_POINTS", "KNN_K", "ISO_N_ESTIMATORS"}:
            if not number.is_integer():
                raise ValueError(f"{name} must be an integer")
            validated[name] = int(number)
        else:
            validated[name] = number
    return validated


def load_config() -> tuple[dict[str, int | float], list[dict[str, Any]]]:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_PARAMS), []

    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        saved = json.load(config_file)
    if not isinstance(saved, dict):
        raise ValueError("hyperparams.json must contain a JSON object")

    params = dict(DEFAULT_PARAMS)
    params.update(validate_params(saved.get("params", {})))
    history = saved.get("history", [])
    if not isinstance(history, list):
        raise ValueError("hyperparams.json history must be a list")
    return params, history


def apply_config(namespace: dict[str, Any]) -> None:
    params, _ = load_config()
    namespace.update(params)
