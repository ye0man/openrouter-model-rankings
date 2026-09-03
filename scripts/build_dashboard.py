#!/usr/bin/env python3
"""Generate a static HTML dashboard from the processed rankings JSON."""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PUBLIC_DIR = BASE_DIR / "public"
PUBLIC_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="OpenRouter model rankings by task — quality, speed, and value." />
  <title>OpenRouter Model Rankings | jakedat.com</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <div id="app">
    <header class="site-header">
      <p class="prefix small-caps"><span class="hash-prefix">0x</span>rankings</p>
      <h1>OpenRouter Model Rankings</h1>
      <p class="subtitle">Pick the right model for the right task — at a glance.</p>
      <p class="meta">Last updated: <span id="last-updated">{last_updated}</span></p>
    </header>

    <section class="controls" aria-label="Filters">
      <div class="control-group">
        <label for="arena-select">Design Arena</label>
        <select id="arena-select">
          <option value="models" selected>Models</option>
          <option value="builders">Builders</option>
          <option value="agents">Agents</option>
        </select>
      </div>
      <div class="control-group">
        <label for="max-input-cost">Max input $/M</label>
        <input type="number" id="max-input-cost" min="0" step="0.1" placeholder="Any" />
      </div>
      <div class="control-group">
        <label for="max-output-cost">Max output $/M</label>
        <input type="number" id="max-output-cost" min="0" step="0.1" placeholder="Any" />
      </div>
      <div class="control-group">
        <label for="min-context">Min context</label>
        <input type="number" id="min-context" min="0" step="1000" placeholder="Any" />
      </div>
      <div class="control-group checkbox-group">
        <label><input type="checkbox" id="require-tools" /> Tools</label>
        <label><input type="checkbox" id="require-vision" /> Vision</label>
        <label><input type="checkbox" id="require-reasoning" /> Reasoning</label>
      </div>
    </section>

    <main>
      <section id="task-grid" class="task-grid" aria-label="Task grid"></section>

      <section id="detail-panel" class="detail-panel hidden">
        <div class="detail-header">
          <div>
            <h2 id="detail-title">Task detail</h2>
            <p id="detail-subtitle" class="detail-subtitle"></p>
          </div>
          <button id="close-detail" class="close-btn" aria-label="Close detail">×</button>
        </div>

        <div class="quick-picks" id="quick-picks"></div>

        <div class="table-wrap">
          <table class="rankings-table" id="rankings-table">
            <thead>
              <tr>
                <th data-sort="rank" class="sortable">Rank</th>
                <th>Model</th>
                <th data-sort="score" class="sortable">Score</th>
                <th data-sort="quality_percentile" class="sortable">Percentile</th>
                <th data-sort="input_cost_per_1m" class="sortable">In $/M</th>
                <th data-sort="output_cost_per_1m" class="sortable">Out $/M</th>
                <th data-sort="speed_ms" class="sortable">Speed (ms)</th>
                <th data-sort="value_score" class="sortable active-desc">Value</th>
                <th data-sort="context_length" class="sortable">Context</th>
                <th>Features</th>
              </tr>
            </thead>
            <tbody id="rankings-body"></tbody>
          </table>
        </div>
      </section>
    </main>

    <footer class="site-footer">
      <p><span class="hash-prefix">0x</span>jakedat · Data via <a href="https://openrouter.ai" target="_blank" rel="noopener">OpenRouter</a>, <a href="https://artificialanalysis.ai" target="_blank" rel="noopener">Artificial Analysis</a>, and <a href="https://designarena.org" target="_blank" rel="noopener">Design Arena</a>.</p>
    </footer>
  </div>

  <script>
    window.RANKINGS_DATA = {data};
  </script>
  <script src="app.js"></script>
</body>
</html>
"""



def load_data() -> dict:
    path = DATA_DIR / "rankings.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def to_js_json(data: dict) -> str:
    """Safely embed JSON into a JavaScript variable.

    JSON is safe inside a <script> tag as long as the literal '</script>'
    sequence cannot appear. We escape the slash in that sequence and keep
    the raw Unicode characters so JavaScript can parse it directly.
    """
    serialized = json.dumps(data, ensure_ascii=False)
    # Prevent any accidental </script> or <!-- inside JSON from closing the tag.
    serialized = serialized.replace("</", "<\\/")
    return serialized


def main() -> int:
    data = load_data()
    last_updated = data.get("meta", {}).get("as_of", "unknown")

    rendered = HTML_TEMPLATE.format(
        last_updated=html.escape(last_updated),
        data=to_js_json(data),
    )

    output_path = PUBLIC_DIR / "index.html"
    with output_path.open("w", encoding="utf-8") as f:
        f.write(rendered)

    logger.info(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
