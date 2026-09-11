(function () {
  const data = window.RANKINGS_DATA;
  const indicesMeta = data.tasks.indices;
  const designArenaMeta = data.tasks.design_arena;
  const indexKeys = Object.keys(indicesMeta);
  const designKeys = Object.keys(designArenaMeta.models);
  const arenasWithData =
    (data.meta && data.meta.coverage && data.meta.coverage.arenas_with_data) || null;
  const coverageNote = document.getElementById("coverage-note");

  const state = {
    arena: "models",
    activeTask: null,
    taskType: null, // 'index' | 'design'
    sortKey: "value_score",
    sortDir: "desc",
    filters: {
      maxInput: "",
      maxOutput: "",
      minContext: "",
      requireTools: false,
      requireVision: false,
      requireReasoning: false,
    },
  };

  const taskCards = document.getElementById("task-grid");
  const detailPanel = document.getElementById("detail-panel");
  const detailTitle = document.getElementById("detail-title");
  const detailSubtitle = document.getElementById("detail-subtitle");
  const quickPicks = document.getElementById("quick-picks");
  const rankingsBody = document.getElementById("rankings-body");
  const closeDetail = document.getElementById("close-detail");
  const arenaSelect = document.getElementById("arena-select");
  const maxInput = document.getElementById("max-input-cost");
  const maxOutput = document.getElementById("max-output-cost");
  const minContext = document.getElementById("min-context");
  const requireTools = document.getElementById("require-tools");
  const requireVision = document.getElementById("require-vision");
  const requireReasoning = document.getElementById("require-reasoning");

  function formatCurrency(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    if (n === 0) return "$0";
    if (n < 1) return "$" + n.toFixed(3);
    return "$" + n.toFixed(2);
  }

  function formatPerImage(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    if (n === 0) return "$0";
    if (n < 0.01) return "$" + n.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
    return "$" + n.toFixed(4);
  }

  function costClass(n) {
    if (n === null || n === undefined) return "";
    if (n <= 1) return "cost-low";
    if (n <= 5) return "cost-medium";
    return "cost-high";
  }

  function speedClass(ms) {
    if (ms === null || ms === undefined) return "";
    if (ms <= 2000) return "speed-fast";
    if (ms <= 5000) return "speed-medium";
    return "speed-slow";
  }

  function filterItems(items) {
    const f = state.filters;
    return items.filter((item) => {
      if (f.maxInput && item.input_cost_per_1m !== null && item.input_cost_per_1m > parseFloat(f.maxInput)) return false;
      if (f.maxOutput && item.output_cost_per_1m !== null && item.output_cost_per_1m > parseFloat(f.maxOutput)) return false;
      if (f.minContext && item.context_length !== null && item.context_length < parseInt(f.minContext, 10)) return false;
      if (f.requireTools && !item.supports_tools) return false;
      if (f.requireVision && !item.supports_vision) return false;
      if (f.requireReasoning && !item.supports_reasoning) return false;
      return true;
    });
  }

  function getTaskItems(taskKey, taskType) {
    if (taskType === "index") {
      return data.indices[taskKey] || [];
    }
    return (data.design_arena[state.arena] || {})[taskKey] || [];
  }

  function getTaskLabel(taskKey, taskType) {
    if (taskType === "index") {
      return indicesMeta[taskKey]?.label || taskKey;
    }
    return designArenaMeta[state.arena]?.[taskKey]?.label || taskKey;
  }

  function clampPercentile(p) {
    return Math.max(0, Math.min(100, p || 0));
  }

  function findBestOverall(items) {
    let best = null;
    for (const item of items) {
      if (!best || item.score > best.score) best = item;
    }
    return best;
  }

  function findBestValue(items) {
    let best = null;
    for (const item of items) {
      if (item.value_score === null || item.value_score === undefined || item.value_score <= 0) continue;
      if (!best || item.value_score > best.value_score) best = item;
    }
    return best;
  }

  function findFastest(items) {
    let best = null;
    for (const item of items) {
      if (item.speed_ms === null || item.speed_ms === undefined) continue;
      if (!best || item.speed_ms < best.speed_ms) best = item;
    }
    return best;
  }

  function hasActiveFilters() {
    return (
      state.filters.maxInput !== "" ||
      state.filters.maxOutput !== "" ||
      state.filters.minContext !== "" ||
      state.filters.requireTools ||
      state.filters.requireVision ||
      state.filters.requireReasoning
    );
  }

  function renderTaskGrid() {
    taskCards.innerHTML = "";

    const allTasks = [
      ...indexKeys.map((k) => ({ key: k, type: "index" })),
      ...designKeys.map((k) => ({ key: k, type: "design" })),
    ];

    for (const task of allTasks) {
      const allItems = getTaskItems(task.key, task.type);
      const items = filterItems(allItems);
      const label = getTaskLabel(task.key, task.type);

      const card = document.createElement("div");
      card.className = "task-card";
      if (allItems.length === 0) {
        card.classList.add("task-card-empty");
      } else {
        card.setAttribute("role", "button");
        card.setAttribute("tabindex", "0");
        card.addEventListener("click", () => openDetail(task.key, task.type));
        card.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") openDetail(task.key, task.type);
        });
      }

      const bestOverall = findBestOverall(items);
      const bestValue = findBestValue(items);

      let html = `<h3>${escapeHtml(label)}</h3>`;

      if (bestOverall) {
        html += `<div class="task-featured">`;
        if (bestValue && bestValue !== bestOverall) {
          html += featuredModelHtml("Best Overall", "best-overall", bestOverall);
          html += featuredModelHtml("Best Value", "best-value", bestValue);
        } else if (bestValue) {
          html += featuredModelHtml("Best Overall &amp; Best Value", "best-overall best-value", bestOverall);
        } else {
          html += featuredModelHtml("Best Overall", "best-overall", bestOverall);
        }
        html += `</div>`;
      } else if (allItems.length === 0) {
        html += `<div class="empty-state">No data for this arena</div>`;
      } else if (hasActiveFilters()) {
        html += `<div class="empty-state">No models match filters</div>`;
      } else {
        html += `<div class="empty-state">No data available</div>`;
      }

      card.innerHTML = html;
      taskCards.appendChild(card);
    }
  }

  function modelStatsHtml(item) {
    const pct = Math.round(clampPercentile(item.quality_percentile));
    const qualityLabel = item.quality_metric === "elo" ? "Elo" : "Score";
    let rows = `<div class="featured-stat"><dt>${qualityLabel}</dt><dd><span class="stat-value">${item.score}</span><span class="stat-sub">${pct}% pct</span></dd></div>`;
    if (item.cost_basis === "per_image" && item.image_cost_per_image !== null && item.image_cost_per_image !== undefined) {
      rows += `<div class="featured-stat"><dt>Image</dt><dd><span class="stat-value">${formatPerImage(item.image_cost_per_image)}</span><span class="stat-sub">per image</span></dd></div>`;
    } else {
      rows += `<div class="featured-stat"><dt>Input</dt><dd><span class="stat-value">${formatCurrency(item.input_cost_per_1m)}</span><span class="stat-sub">/M</span></dd></div>`;
      rows += `<div class="featured-stat"><dt>Output</dt><dd><span class="stat-value">${formatCurrency(item.output_cost_per_1m)}</span><span class="stat-sub">/M</span></dd></div>`;
    }
    return `<dl class="featured-stats">${rows}</dl>`;
  }

  function featuredModelHtml(label, cls, item) {
    const unmatched = item.catalog_matched === false;
    return `
      <div class="featured-model ${cls}">
        <div class="featured-label">${label}</div>
        <div class="featured-name" title="${escapeHtml(item.slug || "")}">${escapeHtml(item.name)}</div>
        <div class="featured-provider">${escapeHtml(item.provider)}${unmatched ? " · unmatched benchmark entry" : ""}</div>
        ${modelStatsHtml(item)}
      </div>
    `;
  }

  function formatMetric(item) {
    if (item.quality_metric === "elo") return `ELO ${item.score}`;
    const label = indicesMeta[item.quality_metric]?.label || item.quality_metric;
    return `${label} ${item.score}`;
  }

  function openDetail(taskKey, taskType) {
    state.activeTask = taskKey;
    state.taskType = taskType;
    state.sortKey = "value_score";
    state.sortDir = "desc";
    detailPanel.classList.remove("hidden");
    renderDetail();
    detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function closeDetailPanel() {
    state.activeTask = null;
    state.taskType = null;
    detailPanel.classList.add("hidden");
  }

  function sortItems(items) {
    const key = state.sortKey;
    const dir = state.sortDir === "asc" ? 1 : -1;
    const isAsc = state.sortDir === "asc";

    return items.slice().sort((a, b) => {
      let va = a[key];
      let vb = b[key];

      // Null handling: sort nulls to bottom regardless of direction
      const aNull = va === null || va === undefined || Number.isNaN(va);
      const bNull = vb === null || vb === undefined || Number.isNaN(vb);
      if (aNull && bNull) return 0;
      if (aNull) return 1;
      if (bNull) return -1;

      // For cost fields ascending means cheaper first, so invert dir
      let effectiveDir = dir;
      if (["input_cost_per_1m", "output_cost_per_1m", "speed_ms"].includes(key)) {
        effectiveDir = isAsc ? -1 : 1;
      }

      if (va < vb) return -1 * effectiveDir;
      if (va > vb) return 1 * effectiveDir;
      // stable tie-break by quality score descending
      return b.score - a.score;
    });
  }

  function renderDetail() {
    if (!state.activeTask) return;
    const items = filterItems(getTaskItems(state.activeTask, state.taskType));
    const sorted = sortItems(items);
    const label = getTaskLabel(state.activeTask, state.taskType);
    const arenaLabel = state.taskType === "design" ? ` — ${capitalize(state.arena)} arena` : "";

    detailTitle.textContent = label;
    detailSubtitle.textContent = `${sorted.length} model${sorted.length === 1 ? "" : "s"}${arenaLabel}`;

    // Quick picks
    const bestOverall = findBestOverall(sorted);
    const bestValue = findBestValue(sorted);
    const bestSpeed = findFastest(sorted);
    quickPicks.innerHTML = "";

    if (bestOverall) {
      quickPicks.appendChild(createPickCard("Best Overall", bestOverall, "best-overall", "score"));
    }
    if (bestValue && bestValue !== bestOverall) {
      quickPicks.appendChild(createPickCard("Best Value", bestValue, "best-value", "value_score"));
    }
    if (bestSpeed && bestSpeed !== bestOverall) {
      quickPicks.appendChild(createPickCard("Fastest", bestSpeed, "fastest", "speed_ms"));
    }

    // Table
    rankingsBody.innerHTML = "";
    for (const item of sorted) {
      const tr = document.createElement("tr");
      const scorePct = clampPercentile(item.quality_percentile);
      tr.innerHTML = `
        <td>${item.rank || "—"}</td>
        <td>
          <div class="model-cell">
            <span class="model-name">${escapeHtml(item.name)}</span>
            <span class="model-slug">${escapeHtml(item.slug)}</span>
          </div>
        </td>
        <td>
          <span class="score-bar" aria-hidden="true"><span class="score-bar-fill" style="width: ${scorePct}%"></span></span>
          ${item.score}
        </td>
        <td><span class="percentile" title="Beats ${scorePct}% of models in this task">${scorePct}%</span></td>
        <td class="${costClass(item.input_cost_per_1m)}">${formatCurrency(item.input_cost_per_1m)}</td>
        <td class="${costClass(item.output_cost_per_1m)}">${formatCurrency(item.output_cost_per_1m)}</td>
        <td class="${speedClass(item.speed_ms)}">${item.speed_ms !== null && item.speed_ms !== undefined ? item.speed_ms.toLocaleString() : "—"}</td>
        <td>${item.value_score !== null && item.value_score !== undefined ? item.value_score.toFixed(1) : "—"}</td>
        <td>${item.context_length ? item.context_length.toLocaleString() : "—"}</td>
        <td>${featureBadges(item)}</td>
      `;
      rankingsBody.appendChild(tr);
    }

    updateSortIndicators();
  }

  const createPickCard = (label, item, cls, highlightKey) => {
    const div = document.createElement("div");
    div.className = `pick-card ${cls}`;
    const value = item[highlightKey];
    let valueStr = "";
    if (highlightKey === "speed_ms") {
      valueStr = `${value.toLocaleString()} ms`;
    } else if (highlightKey === "value_score") {
      valueStr = value.toFixed(1);
    } else {
      valueStr = `${value}`;
    }
    div.innerHTML = `
      <div class="pick-label">${label}</div>
      <div class="pick-name">${escapeHtml(item.name)}</div>
      <div class="pick-meta">${highlightKey === "value_score" ? formatMetric(item) + " · " : ""}${formatCurrency(item.input_cost_per_1m)} / ${formatCurrency(item.output_cost_per_1m)} · ${valueStr}</div>
    `;
    return div;
  };

  function featureBadges(item) {
    const badges = [];
    if (item.supports_tools) badges.push(`<span class="badge active">Tools</span>`);
    if (item.supports_vision) badges.push(`<span class="badge active">Vision</span>`);
    if (item.supports_reasoning) badges.push(`<span class="badge active">Reasoning</span>`);
    if (item.supports_structured) badges.push(`<span class="badge active">JSON</span>`);
    if (!badges.length) badges.push(`<span class="badge">Text</span>`);
    return `<div class="feature-badges">${badges.join("")}</div>`;
  }

  function updateSortIndicators() {
    document.querySelectorAll(".rankings-table th").forEach((th) => {
      th.classList.remove("active-asc", "active-desc");
      const key = th.dataset.sort;
      if (key && key === state.sortKey) {
        th.classList.add(state.sortDir === "asc" ? "active-asc" : "active-desc");
      }
    });
  }

  function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Event listeners
  arenaSelect.addEventListener("change", (e) => {
    state.arena = e.target.value;
    renderTaskGrid();
    if (state.activeTask && state.taskType === "design") {
      renderDetail();
    }
  });

  function onFilterChange() {
    state.filters.maxInput = maxInput.value;
    state.filters.maxOutput = maxOutput.value;
    state.filters.minContext = minContext.value;
    state.filters.requireTools = requireTools.checked;
    state.filters.requireVision = requireVision.checked;
    state.filters.requireReasoning = requireReasoning.checked;
    renderTaskGrid();
    if (state.activeTask) renderDetail();
  }

  [maxInput, maxOutput, minContext, requireTools, requireVision, requireReasoning].forEach((el) => {
    el.addEventListener("input", onFilterChange);
    el.addEventListener("change", onFilterChange);
  });

  document.querySelector(".rankings-table thead").addEventListener("click", (e) => {
    const th = e.target.closest("th[data-sort]");
    if (!th) return;
    const key = th.dataset.sort;
    if (state.sortKey === key) {
      state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    } else {
      state.sortKey = key;
      state.sortDir = "desc";
    }
    renderDetail();
  });

  closeDetail.addEventListener("click", closeDetailPanel);

  function configureArenaOptions() {
    if (arenasWithData) {
      Array.from(arenaSelect.options).forEach((opt) => {
        const has = arenasWithData.indexOf(opt.value) !== -1;
        opt.disabled = !has;
        if (!has && !/\(no data\)$/.test(opt.textContent)) {
          opt.textContent = opt.textContent + " (no data)";
        }
      });
      if (arenasWithData.indexOf(state.arena) === -1 && arenasWithData.length) {
        state.arena = arenasWithData[0];
        arenaSelect.value = state.arena;
      }
    }
    renderCoverageNote();
  }

  function renderCoverageNote() {
    if (!coverageNote) return;
    const aa = data.meta && data.meta.coverage && data.meta.coverage.artificial_analysis;
    if (!aa) return;
    const matched = (aa.matched_exact || 0) + (aa.matched_alias || 0) + (aa.synthesized || 0);
    coverageNote.textContent =
      "Rankings include " +
      matched +
      " of " +
      aa.rows +
      " Artificial Analysis rows matched to the OpenRouter catalog. Models without published benchmark data are not ranked.";
  }

  // Initialize
  configureArenaOptions();
  renderTaskGrid();
})();
