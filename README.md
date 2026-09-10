# OpenRouter Model Rankings

A static, embeddable dashboard that answers the question: *“Which OpenRouter model should I use for this task?”*

It ranks models by task-specific quality, cost, and speed using data from OpenRouter, Artificial Analysis, and Design Arena.

## What it shows

- **Task grid** — at-a-glance cards for common tasks. Each card features two champions with equal billing:
  - **Best Overall** — the highest raw benchmark score in that task (cost-agnostic).
  - **Best Value** — the best cost/performance tradeoff (see scoring below).
  - Tasks: Code / Software Dev, General Intelligence / Reasoning, Agentic Workflows, UI Components, Web / Games, 3D Graphics, Data Visualization, Image Design.
- **Arena selector** — switch between `models`, `builders`, and `agents` for Design Arena tasks. Only arenas that currently publish data for the configured categories are selectable; the others are disabled and marked "(no data)".
- **Filters** — max input/output cost, minimum context length, required features (tools, vision, reasoning).
- **Detail view** — sortable table with quality score, quality percentile, cost, speed, value score, context length, and feature badges.
- **Quick picks** — best overall, best value, and fastest model for each task.

## How scoring works

- **Best Overall** is the model with the highest raw benchmark score in the task. It ignores cost and speed:
  - Artificial Analysis tasks use `coding_index`, `intelligence_index`, or `agentic_index`.
  - Design Arena tasks use the category Elo.
- **Quality percentile** is rank-based within each task category (rank 1 = 100th percentile).
- **Value score (0–100)** is a bounded cost/performance tradeoff, normalized within each task so the best tradeoff is 100:
  - `penalty = max(0, (quality_percentile / 100)² − 0.25)` — cheap but low-quality models score zero.
  - `cost_factor = min(2, 1 + ln(1 + cost) / ln(1 + cost_ref))`, where `cost_ref` is the 90th-percentile cost within the task.
  - `value_raw = quality_percentile × penalty / cost_factor`, then min–max normalized across the task to `0–100`.
  - Bounding `cost_factor` (instead of dividing by `ln(1 + cost)`) keeps free and per-image models from producing astronomically large scores.
- **Cost basis** — text models use a 70% input / 30% output blend per 1M tokens; image-output models use their per-image price (`image_output`, falling back to `image_token`). If no price is available, the model has no value score and only appears under Best Overall.
- **Benchmark matching** — benchmark rows are joined to the OpenRouter catalog by exact slug first, then by a date/variant-normalized alias (e.g. `anthropic/claude-fable-5.1-20260831` → `anthropic/claude-fable-5.1`). Rows that still cannot be matched are retained using the pricing supplied in the benchmark row and flagged `catalog_matched: false`. Match counts are recorded in `meta.coverage`.
- **Speed** uses Design Arena's `avg_generation_time_ms` (lower is better).

## Repository structure

```
openrouter-model-rankings/
├── .github/workflows/daily-update.yml  # GitHub Actions: fetch, build, deploy
├── scripts/
│   ├── fetch_data.py                   # fetch + normalize + score data
│   └── build_dashboard.py              # generate public/index.html
├── public/
│   ├── index.html                      # generated dashboard
│   ├── app.js                          # client-side interactivity
│   └── style.css                       # dashboard styles
├── data/
│   ├── models.json                     # generated model metadata
│   └── rankings.json                   # generated rankings
├── requirements.txt
└── README.md
```

## Local development

1. Clone the repo:

   ```bash
   git clone https://github.com/YOUR_USERNAME/openrouter-model-rankings.git
   cd openrouter-model-rankings
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Set your OpenRouter API key. Either create a `.env` file:

   ```bash
   cp .env.example .env
   # then edit .env and add your key
   ```

   or export it directly:

   ```bash
   export OPENROUTER_API_KEY="sk-or-v1-..."
   ```

4. Fetch data and build the dashboard:

   ```bash
   python scripts/fetch_data.py
   python scripts/build_dashboard.py
   ```

5. Preview locally:

   ```bash
   cd public
   python -m http.server 8123
   ```

   Open <http://localhost:8123>.

## Deploy on GitHub Pages

1. Push this repo to GitHub.
2. Go to **Settings → Secrets and variables → Actions** and add a repository secret named `OPENROUTER_API_KEY`.
3. Go to **Settings → Pages** and set **Source** to **GitHub Actions**.
4. The `daily-update.yml` workflow will run every day at 06:00 UTC and on demand via workflow dispatch.
5. Your site will be published at `https://YOUR_USERNAME.github.io/openrouter-model-rankings/`.

## Embed on your site

Add an iframe where you want it to appear:

```html
<iframe
  src="https://YOUR_USERNAME.github.io/openrouter-model-rankings/"
  width="100%"
  height="900"
  style="border: none;"
  title="OpenRouter Model Rankings">
</iframe>
```

## Data sources & attribution

- [OpenRouter](https://openrouter.ai)
- [Artificial Analysis](https://artificialanalysis.ai)
- [Design Arena](https://designarena.org)

## License

MIT
