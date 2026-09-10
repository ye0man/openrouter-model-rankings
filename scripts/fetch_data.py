#!/usr/bin/env python3
"""
Fetch model and benchmark data from OpenRouter, merge it, compute
quality percentiles and cost/performance value scores, and write JSON
artifacts for the static dashboard generator.

Benchmark rows are joined to the OpenRouter catalog by exact slug first
and then by a date/variant-normalized alias, so dated benchmark slugs
(e.g. ``anthropic/claude-fable-5.1-20260831``) resolve to the canonical
catalog model (``anthropic/claude-fable-5.1``). Rows that still cannot be
resolved are retained using the pricing shipped in the benchmark row, so
no benchmark data is silently dropped. Coverage statistics are written
into ``meta.coverage``.

Expected environment variable:
    OPENROUTER_API_KEY
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import time
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
    """Return a non-negative USD price, or None if unavailable."""
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
        "image_output_price": parse_price(pricing.get("image_output")),
        "image_token_price": parse_price(pricing.get("image_token")),
        "catalog_matched": True,
        "raw": raw,  # keep full record for debugging
    }


def synthesize_model(slug: str, row: dict[str, Any], is_image: bool = False) -> dict[str, Any]:
    """Build a minimal model record from a benchmark row's own pricing.

    Used when a benchmark slug cannot be matched to the OpenRouter catalog
    (for example retired models). Keeps the row in the rankings instead of
    dropping it silently, but marks it as unmatched so the UI can be honest
    about missing capability metadata.
    """
    pricing = row.get("pricing") or {}
    provider = slug.split("/")[0] if slug and "/" in slug else ""
    name = row.get("display_name") or (slug.split("/")[-1] if slug else slug)
    return {
        "id": slug,
        "name": name,
        "provider": provider,
        "canonical_slug": slug,
        "context_length": None,
        "description": "",
        "input_modalities": [],
        "output_modalities": ["image"] if is_image else ["text"],
        "supports_tools": False,
        "supports_reasoning": False,
        "supports_vision": False,
        "supports_structured": False,
        "prompt_price_per_token": parse_price(pricing.get("prompt")),
        "completion_price_per_token": parse_price(pricing.get("completion")),
        "request_price": parse_price(pricing.get("request")),
        "image_output_price": parse_price(pricing.get("image_output")),
        "image_token_price": parse_price(pricing.get("image_token")),
        "catalog_matched": False,
    }


def build_models_map(models: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a map keyed by model id."""
    return {m["id"]: normalize_model(m) for m in models if m.get("id")}


# Trailing variant/date markers used to reconcile dated benchmark slugs
# with canonical OpenRouter model ids.
_VARIANT_SUFFIX = re.compile(r":(free|batch|nitro|extended|thinking|online|floor)$")
_DATE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$|-\d{8}$|-\d{2}-\d{2}$|-\d{4}$")


def normalize_slug(slug: str | None) -> str:
    """Normalize a slug for alias matching (strip variants and date stamps)."""
    s = str(slug or "").strip().lower()
    s = _VARIANT_SUFFIX.sub("", s)
    for _ in range(2):
        stripped = _DATE_SUFFIX.sub("", s)
        if stripped == s:
            break
        s = stripped
    return s


def build_alias_index(models: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Map normalized slugs to the catalog models that share them."""
    index: dict[str, list[dict[str, Any]]] = {}
    for model in models.values():
        for raw_slug in (model.get("id"), model.get("canonical_slug")):
            key = normalize_slug(raw_slug)
            if not key:
                continue
            bucket = index.setdefault(key, [])
            if model not in bucket:
                bucket.append(model)
    return index


def resolve_model(
    slug: str, models: dict[str, dict[str, Any]], alias_index: dict[str, list[dict[str, Any]]]
) -> tuple[dict[str, Any] | None, str]:
    """Resolve a benchmark slug to a catalog model.

    Returns (model, match_type) where match_type is one of ``exact``,
    ``alias`` or ``unmatched``.
    """
    if slug in models:
        return models[slug], "exact"
    candidates = alias_index.get(normalize_slug(slug))
    if candidates:
        # Prefer canonical ids over "~latest" pointers and ":variant" routes.
        ranked = sorted(
            candidates,
            key=lambda m: (
                "~" in (m.get("id") or ""),
                ":" in (m.get("id") or ""),
                len(m.get("id") or ""),
            ),
        )
        return ranked[0], "alias"
    return None, "unmatched"


def compute_cost(model: dict[str, Any]) -> tuple[float | None, str | None]:
    """Return the scalar cost used for value scoring and its basis.

    Image-output models use their per-image price when available
    (``per_image``); text models use a 70/30 input/output blend per 1M
    tokens (``per_1m_tokens``). Returns (None, None) when no usable price
    exists.
    """
    prompt = model.get("prompt_price_per_token")
    completion = model.get("completion_price_per_token")
    image_price = model.get("image_output_price")
    if image_price is None:
        image_price = model.get("image_token_price")

    is_image = "image" in (model.get("output_modalities") or [])
    if is_image and image_price is not None:
        return max(float(image_price), 0.0), "per_image"

    if prompt is None or completion is None:
        if image_price is not None:
            return max(float(image_price), 0.0), "per_image"
        return None, None

    input_m = prompt * 1_000_000
    output_m = completion * 1_000_000
    blended = 0.7 * input_m + 0.3 * output_m
    # Floor so free models do not produce a zero/negative log term.
    return max(blended, 0.001), "per_1m_tokens"


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
# Cost reference point (per-task quantile) used to bound the cost divisor.
VALUE_COST_REF_QUANTILE = 0.9


def _quantile(sorted_values: list[float], q: float) -> float | None:
    """Linear-interpolated quantile of an already-sorted list."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_values[lo]
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def assign_value_scores(items: list[dict[str, Any]]) -> None:
    """Assign a normalized 0..100 value score within a task.

    value_raw = quality_percentile * penalty / cost_factor
    where penalty = max(0, (quality_percentile / 100)^2 - floor)
    and   cost_factor = min(2, 1 + ln(1 + cost) / ln(1 + cost_ref))

    The raw scores are then min-max normalized across the task so the
    resulting value score is an interpretable 0..100 (best tradeoff = 100).
    Bounding the cost divisor via a per-task reference cost prevents free
    models from producing astronomically large scores.
    """
    costs = sorted(i["value_cost"] for i in items if i.get("value_cost") is not None)
    cost_ref = _quantile(costs, VALUE_COST_REF_QUANTILE) or 0.0
    log_ref = math.log1p(cost_ref)

    raw: list[tuple[int, float]] = []
    for idx, item in enumerate(items):
        cost = item.get("value_cost")
        if cost is None:
            item["value_score"] = None
            continue
        qp = item.get("quality_percentile") or 0.0
        penalty = max(0.0, (qp / 100.0) ** 2 - VALUE_PENALTY_FLOOR)
        cost_factor = 1.0 + (math.log1p(cost) / log_ref if log_ref > 0 else 0.0)
        cost_factor = min(cost_factor, 2.0)
        raw.append((idx, qp * penalty / cost_factor))

    if not raw:
        return
    values = [v for _, v in raw]
    lo, hi = min(values), max(values)
    for idx, value in raw:
        items[idx]["value_score"] = round(100.0 * (value - lo) / (hi - lo), 1) if hi > lo else 100.0


def dedupe_by_name(items: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    """Collapse duplicate model entries (multiple routes/slugs) by name."""
    best: dict[str, dict[str, Any]] = {}
    removed = 0
    for item in items:
        key = (item.get("name") or item.get("slug") or "").strip().lower()
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        removed += 1
        if item.get("score", 0) > current.get("score", 0):
            best[key] = item
    if removed:
        logger.info(f"Deduped {removed} duplicate entr{'y' if removed == 1 else 'ies'} in {label}")
    return list(best.values())


def build_ranking_item(
    slug: str,
    model: dict[str, Any],
    score: float,
    metric: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single ranking entry with cost and capability metadata."""
    cost, basis = compute_cost(model)
    prompt = model.get("prompt_price_per_token")
    completion = model.get("completion_price_per_token")
    image_price = model.get("image_output_price")
    if image_price is None:
        image_price = model.get("image_token_price")

    item: dict[str, Any] = {
        "slug": slug,
        "name": model.get("name") or slug,
        "provider": model.get("provider") or "",
        "score": score,
        "quality_metric": metric,
        "value_cost": cost,
        "cost_basis": basis,
        "avg_cost_per_1m": round(cost, 4) if (cost is not None and basis == "per_1m_tokens") else None,
        "image_cost_per_image": round(float(image_price), 6) if image_price is not None else None,
        "input_cost_per_1m": round(prompt * 1_000_000, 4) if prompt is not None else None,
        "output_cost_per_1m": round(completion * 1_000_000, 4) if completion is not None else None,
        "context_length": model.get("context_length"),
        "supports_tools": bool(model.get("supports_tools")),
        "supports_reasoning": bool(model.get("supports_reasoning")),
        "supports_vision": bool(model.get("supports_vision")),
        "supports_structured": bool(model.get("supports_structured")),
        "catalog_matched": bool(model.get("catalog_matched", True)),
        "speed_ms": None,
    }
    if extra:
        item.update(extra)
    return item


def finalize_items(items: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    """Dedupe, score, sort and rank a task's items in place."""
    items = dedupe_by_name(items, label)
    compute_quality_percentile(items, "score")
    assign_value_scores(items)
    items.sort(
        key=lambda x: (
            x.get("value_score") is None,
            -(x.get("value_score") or 0.0),
            -x["score"],
        )
    )
    for idx, item in enumerate(items, start=1):
        item["rank"] = idx
    return items


def build_index_rankings(
    rows: list[dict[str, Any]],
    models: dict[str, dict[str, Any]],
    alias_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Build rankings for Artificial Analysis indices."""
    rankings: dict[str, list[dict[str, Any]]] = {key: [] for key in AA_INDICES}
    coverage: dict[str, Any] = {
        "rows": len(rows),
        "matched_exact": 0,
        "matched_alias": 0,
        "synthesized": 0,
        "unmatched_examples": [],
    }

    for row in rows:
        slug = row.get("model_permaslug")
        if not slug:
            continue
        model, match = resolve_model(slug, models, alias_index)
        if model is None:
            model = synthesize_model(slug, row)
            coverage["synthesized"] += 1
            if len(coverage["unmatched_examples"]) < 10:
                coverage["unmatched_examples"].append(slug)
        elif match == "exact":
            coverage["matched_exact"] += 1
        else:
            coverage["matched_alias"] += 1

        for key in AA_INDICES:
            score = row.get(key)
            if score is None:
                continue
            rankings[key].append(build_ranking_item(slug, model, round(float(score), 2), key))

    for key, items in rankings.items():
        rankings[key] = finalize_items(items, key)
        logger.info(f"{key}: {len(rankings[key])} ranked models")
    return rankings, coverage


def build_design_arena_rankings(
    rows: list[dict[str, Any]],
    models: dict[str, dict[str, Any]],
    alias_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, Any]]:
    """Build rankings for Design Arena categories grouped by arena."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
        arena: {cat: [] for cat in BENCHMARK_CATEGORIES} for arena in ARENAS
    }
    coverage: dict[str, Any] = {
        arena: {
            "rows": 0,
            "entries": 0,
            "matched_exact": 0,
            "matched_alias": 0,
            "synthesized": 0,
            "categories": {cat: 0 for cat in BENCHMARK_CATEGORIES},
        }
        for arena in ARENAS
    }

    for row in rows:
        arena = row.get("arena")
        if arena not in grouped:
            continue
        coverage[arena]["rows"] += 1

        category = row.get("category")
        if category not in grouped[arena]:
            continue
        slug = row.get("model_permaslug")
        if not slug:
            continue
        elo = row.get("elo")
        if elo is None:
            continue

        model, match = resolve_model(slug, models, alias_index)
        if model is None:
            model = synthesize_model(slug, row, is_image=(category == "image"))
            coverage[arena]["synthesized"] += 1
        elif match == "exact":
            coverage[arena]["matched_exact"] += 1
        else:
            coverage[arena]["matched_alias"] += 1

        speed = row.get("avg_generation_time_ms")
        extra = {
            "win_rate": row.get("win_rate"),
            "speed_ms": round(float(speed), 0) if speed is not None else None,
        }
        grouped[arena][category].append(
            build_ranking_item(slug, model, round(float(elo), 1), "elo", extra)
        )

    for arena in grouped:
        for category, items in grouped[arena].items():
            finalized = finalize_items(items, f"{arena}/{category}")
            grouped[arena][category] = finalized
            coverage[arena]["categories"][category] = len(finalized)
        coverage[arena]["entries"] = sum(coverage[arena]["categories"].values())
        logger.info(
            f"design-arena/{arena}: {coverage[arena]['rows']} rows fetched, "
            f"{coverage[arena]['entries']} ranked in configured categories"
        )
    return grouped, coverage


def main() -> int:
    api_key = get_api_key()

    logger.info("Fetching model catalog")
    raw_models = fetch_all_models(api_key)
    models = build_models_map(raw_models)
    alias_index = build_alias_index(models)

    logger.info("Fetching Artificial Analysis benchmarks")
    aa_rows = fetch_benchmarks("artificial-analysis", api_key=api_key)

    logger.info("Fetching Design Arena benchmarks")
    da_rows: list[dict[str, Any]] = []
    for arena in ARENAS:
        da_rows.extend(fetch_benchmarks("design-arena", api_key=api_key, arena=arena))
        time.sleep(1)

    index_rankings, aa_coverage = build_index_rankings(aa_rows, models, alias_index)
    design_rankings, da_coverage = build_design_arena_rankings(da_rows, models, alias_index)

    arenas_with_data = [arena for arena in ARENAS if da_coverage[arena]["entries"] > 0]

    meta = {
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_count": len(models),
        "task_count": len(AA_INDICES) + len(ARENAS) * len(BENCHMARK_CATEGORIES),
        "coverage": {
            "artificial_analysis": aa_coverage,
            "design_arena": da_coverage,
            "arenas_with_data": arenas_with_data,
        },
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
