#!/usr/bin/env python3
"""
Fetch model and benchmark data from OpenRouter, merge it, compute
quality percentiles and value scores, and write JSON artifacts for the
static dashboard generator.

Expected environment variable:
    OPENROUTER_API_KEY
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Load OPENROUTER_API_KEY from a .env file when running locally.
load_dotenv(BASE_DIR / ".env")

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
BENCHMARK_CATEGORIES = {
    "uicomponent": "UI Components",
    "gamedev": "Web / Games",
    "3d": "3D Graphics",
    "dataviz": "Data Visualization",
    "image": "Image Design",
}
ARENAS = ["models", "builders", "agents"]
AA_INDICES = {
    "coding_index": "Code / Software Dev",
    "intelligence_index": "General Intelligence / Reasoning",
    "agentic_index": "Agentic Workflows",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        logger.error("OPENROUTER_API_KEY is not set")
        sys.exit(1)
    return key


def api_get(path: str, params: dict[str, Any] | None = None, api_key: str | None = None) -> Any:
    """Make an authenticated GET request to the OpenRouter API."""
    if api_key is None:
        api_key = get_api_key()
    url = f"{OPENROUTER_BASE}{path}"
    headers = {"Authorization": f"Bearer {api_key}"}
    logger.info(f"GET {url} params={params}")
    resp = requests.get(url, headers=headers, params=params, timeout=60)
    if resp.status_code == 429:
        logger.warning("Rate limited; sleeping 10s before retry")
        time.sleep(10)
        resp = requests.get(url, headers=headers, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def fetch_all_models(api_key: str) -> list[dict[str, Any]]:
    """Fetch the full model catalog for text and image output models."""
    models: list[dict[str, Any]] = []
    offset = 0
    limit = 500
    while True:
        payload = api_get(
            "/models",
            {"limit": limit, "offset": offset, "output_modalities": "text,image"},
            api_key=api_key,
        )
        batch = payload.get("data", [])
        models.extend(batch)
        next_link = (payload.get("links") or {}).get("next")
        if not batch or not next_link:
            break
        offset += limit
    logger.info(f"Fetched {len(models)} models")
    return models


def fetch_benchmarks(source: str, api_key: str, **extra: Any) -> list[dict[str, Any]]:
    """Fetch all benchmark rows for a source."""
    params: dict[str, Any] = {"source": source, **extra}
    payload = api_get("/benchmarks", params, api_key=api_key)
    rows = payload.get("data", [])
    logger.info(f"Fetched {len(rows)} rows from source={source} params={extra}")
    return rows


def parse_price(value: Any) -> float | None:
    """Return price in USD per token, or None if unavailable."""
    if value is None:
        return None
    try:
        price = float(str(value))
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None
    return price


def normalize_model(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the raw OpenRouter model object into a clean shape."""
    pricing = raw.get("pricing") or {}
    prompt_price = parse_price(pricing.get("prompt"))
    completion_price = parse_price(pricing.get("completion"))

    architecture = raw.get("architecture") or {}
    input_modalities = architecture.get("input_modalities") or []
    output_modalities = architecture.get("output_modalities") or []
    supported_parameters = raw.get("supported_parameters") or []
    reasoning_config = raw.get("reasoning") or {}

    # Capability flags
    supports_tools = "tools" in supported_parameters
    supports_reasoning = (
        "reasoning" in supported_parameters
        or reasoning_config.get("mandatory") is True
        or reasoning_config.get("default_enabled") is True
    )
    supports_vision = "image" in input_modalities
    supports_structured = "structured_outputs" in supported_parameters

    return {
        "id": raw.get("id"),
        "name": raw.get("name") or raw.get("id", "").split("/")[-1],
        "provider": raw.get("id", "").split("/")[0] if raw.get("id") else "",
        "canonical_slug": raw.get("canonical_slug"),
        "context_length": raw.get("context_length"),
        "description": raw.get("description", ""),
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
        "supports_tools": supports_tools,
        "supports_reasoning": supports_reasoning,
        "supports_vision": supports_vision,
        "supports_structured": supports_structured,
        "prompt_price_per_token": prompt_price,
        "completion_price_per_token": completion_price,
        "request_price": parse_price(pricing.get("request")),
        "raw": raw,  # keep full record for debugging
    }


def build_models_map(models: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a map keyed by canonical slug."""
    return {m["id"]: normalize_model(m) for m in models if m.get("id")}


def compute_blended_cost_per_million(model: dict[str, Any]) -> float:
    """Compute blended cost per 1M tokens using a 70/30 input/output split."""
    prompt = model.get("prompt_price_per_token")
    completion = model.get("completion_price_per_token")
    if prompt is None or completion is None:
        return float("inf")
    input_m = prompt * 1_000_000
    output_m = completion * 1_000_000
    blended = 0.7 * input_m + 0.3 * output_m
    # Floor so free models don't explode ln(0)
    return max(blended, 0.001)


def compute_quality_percentile(items: list[dict[str, Any]], key: str) -> None:
    """Mutate items with a 0..100 quality percentile based on key (higher is better)."""
    sorted_items = sorted(items, key=lambda x: x[key], reverse=True)
    n = len(sorted_items)
    if n == 0:
        return
    for idx, item in enumerate(sorted_items):
        # percentile where rank 1 = 100
        item["quality_percentile"] = round(100 * (1 - idx / n), 1)


# Minimum squared-percentile threshold for the quadratic penalty.
# Models at or below the 50th percentile (p/100 <= 0.5) get zero value score;
# above that, the penalty grows quadratically so excellent-but-cheap models
# can still win without dirt-cheap, low-quality models dominating.
VALUE_PENALTY_FLOOR = 0.25


def compute_value_score(item: dict[str, Any], avg_cost: float) -> None:
    """Compute value score with a quadratic quality penalty.

    value = (quality_percentile * penalty) / ln(1 + avg_cost)
    where penalty = max(0, (quality_percentile / 100)^2 - floor)

    This prevents very cheap, low-quality models from getting outsized value
    scores while still rewarding inexpensive, high-quality models.
    """
    qp = item.get("quality_percentile", 0)
    penalty = max(0.0, (qp / 100.0) ** 2 - VALUE_PENALTY_FLOOR)
    try:
        item["value_score"] = round(qp * penalty / math.log1p(avg_cost), 2)
    except (ValueError, ZeroDivisionError):
        item["value_score"] = 0.0


def build_index_rankings(
    rows: list[dict[str, Any]], models: dict[str, dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Build rankings for Artificial Analysis indices."""
    rankings: dict[str, list[dict[str, Any]]] = {key: [] for key in AA_INDICES}
    for row in rows:
        slug = row.get("model_permaslug")
        model = models.get(slug)
        if not model:
            continue
        for key in AA_INDICES:
            score = row.get(key)
            if score is None:
                continue
            avg_cost = compute_blended_cost_per_million(model)
            rankings[key].append(
                {
                    "slug": slug,
                    "name": model["name"],
                    "provider": model["provider"],
                    "score": round(float(score), 2),
                    "quality_metric": key,
                    "avg_cost_per_1m": round(avg_cost, 4) if avg_cost != float("inf") else None,
                    "input_cost_per_1m": round(model["prompt_price_per_token"] * 1_000_000, 4)
                    if model["prompt_price_per_token"] is not None
                    else None,
                    "output_cost_per_1m": round(model["completion_price_per_token"] * 1_000_000, 4)
                    if model["completion_price_per_token"] is not None
                    else None,
                    "context_length": model["context_length"],
                    "supports_tools": model["supports_tools"],
                    "supports_reasoning": model["supports_reasoning"],
                    "supports_vision": model["supports_vision"],
                    "supports_structured": model["supports_structured"],
                    "speed_ms": None,
                }
            )
    for key, items in rankings.items():
        compute_quality_percentile(items, "score")
        for item in items:
            avg_cost = item["avg_cost_per_1m"]
            if avg_cost is not None:
                compute_value_score(item, avg_cost)
        # Sort by value score by default, tie-break by raw score
        items.sort(key=lambda x: (-x.get("value_score", 0), -x["score"]))
        for idx, item in enumerate(items, start=1):
            item["rank"] = idx
    return rankings


def build_design_arena_rankings(
    rows: list[dict[str, Any]], models: dict[str, dict[str, Any]]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Build rankings for Design Arena categories grouped by arena."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
        arena: {cat: [] for cat in BENCHMARK_CATEGORIES} for arena in ARENAS
    }
    for row in rows:
        arena = row.get("arena")
        category = row.get("category")
        if arena not in grouped or category not in grouped[arena]:
            continue
        slug = row.get("model_permaslug")
        model = models.get(slug)
        if not model:
            continue
        elo = row.get("elo")
        if elo is None:
            continue
        avg_cost = compute_blended_cost_per_million(model)
        speed = row.get("avg_generation_time_ms")
        grouped[arena][category].append(
            {
                "slug": slug,
                "name": model["name"],
                "provider": model["provider"],
                "score": round(float(elo), 1),
                "quality_metric": "elo",
                "win_rate": row.get("win_rate"),
                "avg_cost_per_1m": round(avg_cost, 4) if avg_cost != float("inf") else None,
                "input_cost_per_1m": round(model["prompt_price_per_token"] * 1_000_000, 4)
                if model["prompt_price_per_token"] is not None
                else None,
                "output_cost_per_1m": round(model["completion_price_per_token"] * 1_000_000, 4)
                if model["completion_price_per_token"] is not None
                else None,
                "context_length": model["context_length"],
                "supports_tools": model["supports_tools"],
                "supports_reasoning": model["supports_reasoning"],
                "supports_vision": model["supports_vision"],
                "supports_structured": model["supports_structured"],
                "speed_ms": round(float(speed), 0) if speed is not None else None,
            }
        )
    for arena in grouped:
        for category, items in grouped[arena].items():
            compute_quality_percentile(items, "score")
            for item in items:
                avg_cost = item["avg_cost_per_1m"]
                if avg_cost is not None:
                    compute_value_score(item, avg_cost)
            items.sort(key=lambda x: (-x.get("value_score", 0), -x["score"]))
            for idx, item in enumerate(items, start=1):
                item["rank"] = idx
    return grouped


def main() -> int:
    api_key = get_api_key()

    logger.info("Fetching model catalog")
    raw_models = fetch_all_models(api_key)
    models = build_models_map(raw_models)

    logger.info("Fetching Artificial Analysis benchmarks")
    aa_rows = fetch_benchmarks("artificial-analysis", api_key=api_key)

    logger.info("Fetching Design Arena benchmarks")
    da_rows: list[dict[str, Any]] = []
    for arena in ARENAS:
        da_rows.extend(fetch_benchmarks("design-arena", api_key=api_key, arena=arena))
        time.sleep(1)

    index_rankings = build_index_rankings(aa_rows, models)
    design_rankings = build_design_arena_rankings(da_rows, models)

    # Compute some quick cross-task "best" metadata for the task grid.
    meta = {
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_count": len(models),
        "task_count": len(AA_INDICES)
        + len(ARENAS) * len(BENCHMARK_CATEGORIES),
    }

    models_output = {slug: {k: v for k, v in m.items() if k != "raw"} for slug, m in models.items()}

    artifacts = {
        "meta": meta,
        "tasks": {
            "indices": {k: {"label": v} for k, v in AA_INDICES.items()},
            "design_arena": {
                arena: {cat: {"label": label} for cat, label in BENCHMARK_CATEGORIES.items()}
                for arena in ARENAS
            },
        },
        "indices": index_rankings,
        "design_arena": design_rankings,
        "models": models_output,
    }

    models_path = DATA_DIR / "models.json"
    rankings_path = DATA_DIR / "rankings.json"

    with models_path.open("w", encoding="utf-8") as f:
        json.dump({k: v for k, v in artifacts.items() if k != "indices" and k != "design_arena"}, f, indent=2)

    with rankings_path.open("w", encoding="utf-8") as f:
        json.dump(artifacts, f, indent=2)

    logger.info(f"Wrote {models_path}")
    logger.info(f"Wrote {rankings_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
