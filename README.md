# OpenRouter Model Rankings

A static, embeddable dashboard that answers the question: *“Which OpenRouter model should I use for this task?”*

It ranks models by task-specific quality, cost, and speed using data from OpenRouter, Artificial Analysis, and Design Arena.

## What it shows

- **Task grid** — at-a-glance cards for common tasks:
  - Code / Software Dev
  - General Intelligence / Reasoning
  - Agentic Workflows
  - UI Components
  - Web / Games
  - 3D Graphics
  - Data Visualization
  - Image Design
- **Arena selector** — switch between `models`, `builders`, and `agents` for Design Arena tasks. The selected five categories are shown for each arena; if an arena does not currently publish data for a category, that card shows "No data for this arena."
- **Filters** — max input/output cost, minimum context length, required features (tools, vision, reasoning).
- **Detail view** — sortable table with quality score, quality percentile, cost, speed, value score, context length, and feature badges.
- **Quick picks** — best overall, best value, and fastest model for each task.

## How scoring works

- **Quality percentile** is computed within each task category.
- **Value score** = `quality_percentile / ln(1 + avg_cost_per_1m_tokens)`
  - `avg_cost_per_1m_tokens` is a 70% input / 30% output blend.
  - Using `ln(1 + cost)` keeps the score positive and meaningful even for very cheap or free models.
- **Speed** uses Design Arena’s `avg_generation_time_ms` (lower is better).

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
