(() => {
  const dataScript = document.getElementById("timeline-data");
  if (!dataScript) {
    return;
  }

  const DATA = JSON.parse(dataScript.textContent || "{}") || {};
  const PERSONAS = Array.isArray(DATA.personas) ? DATA.personas : [];
  const INSTITUCIONES = Array.isArray(DATA.instituciones) ? DATA.instituciones : [];

  const START_YEAR_DEFAULT = 1997;
  const END_YEAR_DEFAULT = new Date().getFullYear();
  let currentStartYear = START_YEAR_DEFAULT;
  let currentEndYear = END_YEAR_DEFAULT;

  const levelColor = {
    federal: "linear-gradient(135deg, rgba(122,162,255,.85), rgba(122,162,255,.55))",
    estatal: "linear-gradient(135deg, rgba(110,231,183,.85), rgba(110,231,183,.55))",
    municipal: "linear-gradient(135deg, rgba(251,191,36,.85), rgba(251,191,36,.55))",
    partidista: "linear-gradient(135deg, rgba(192,132,252,.85), rgba(192,132,252,.55))",
    otro: "linear-gradient(135deg, rgba(148,163,184,.65), rgba(148,163,184,.35))",
  };

  const entityType = document.getElementById("entityType");
  const entitySelect = document.getElementById("entitySelect");
  const headline = document.getElementById("headline");
  const subhead = document.getElementById("subhead");
  const grid = document.getElementById("grid");
  const rows = document.getElementById("rows");
  const canvas = document.getElementById("canvas");
  const scroller = document.getElementById("scroller");
  const tooltip = document.getElementById("tooltip");
  const panel = document.getElementById("timelinePanel");
  const todayButton = document.getElementById("btnToday");

  if (!entityType || !entitySelect || !headline || !grid || !rows || !canvas || !scroller || !tooltip || !panel) {
    return;
  }

  todayButton?.addEventListener("click", scrollToToday);

  const MONTH_PX = 18;
  const LANE_BAR_H = 28;
  const STACK_GAP = 6;

  let activeBar = null;
  let rafId = null;

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function parseDate(s) {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d || 1);
  }

  function formatMY(s) {
    const d = parseDate(s);
    const months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
    return `${months[d.getMonth()]} ${d.getFullYear()}`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c]
    ));
  }

  function getTimelineBounds(items) {
    let startYear = START_YEAR_DEFAULT;
    let endYear = END_YEAR_DEFAULT;
    if (!items.length) {
      return { startYear, endYear };
    }
    let minYear = endYear;
    let maxYear = startYear;
    items.forEach((it) => {
      const start = parseDate(it.inicio).getFullYear();
      const end = parseDate(it.fin).getFullYear();
      minYear = Math.min(minYear, start);
      maxYear = Math.max(maxYear, end);
    });
    startYear = Math.min(startYear, minYear);
    endYear = Math.max(endYear, maxYear);
    return { startYear, endYear };
  }

  function monthIndex(d, startYear) {
    return (d.getFullYear() - startYear) * 12 + d.getMonth();
  }

  function totalMonths(startYear, endYear) {
    return (endYear - startYear + 1) * 12;
  }

  function getMonthWidth() {
    const styles = getComputedStyle(canvas);
    const value = parseFloat(styles.getPropertyValue("--month-width"));
    return Number.isFinite(value) ? value : 18;
  }

  function setCanvasWidth(startYear, endYear) {
    const w = totalMonths(startYear, endYear) * getMonthWidth() + 20;
    canvas.style.minWidth = `${w}px`;
    canvas.style.width = `${w}px`;
  }

  function buildGrid(startYear, endYear) {
    grid.innerHTML = "";
    setCanvasWidth(startYear, endYear);

    const yearRow = document.createElement("div");
    yearRow.className = "timeline-year-row";
    yearRow.style.left = "0";
    yearRow.style.right = "0";
    yearRow.style.position = "absolute";
    yearRow.style.top = "0";
    yearRow.innerHTML = `<span>${startYear} → ${endYear}</span>`;
    grid.appendChild(yearRow);

    const totalM = totalMonths(startYear, endYear);

    for (let i = 0; i <= totalM; i++) {
      const x = 10 + i * MONTH_PX;
      const isYear = (i % 12 === 0);

      const line = document.createElement("div");
      line.className = isYear ? "timeline-year-line" : "timeline-month-line";
      line.style.left = `${x}px`;
      grid.appendChild(line);
    }

    for (let y = startYear; y <= endYear; y++) {
      const i = (y - startYear) * 12;
      const x = 10 + i * MONTH_PX;

      const lab = document.createElement("div");
      lab.className = "timeline-year-label";
      lab.style.left = `${x + 6}px`;
      lab.textContent = String(y);
      grid.appendChild(lab);
    }
  }

  function stackOverlaps(items, startYear) {
    const segs = items
      .map((it) => {
        const s = parseDate(it.inicio);
        const e = parseDate(it.fin);
        const start = monthIndex(s, startYear);
        const end = monthIndex(e, startYear);
        return { ...it, _start: start, _end: end };
      })
      .sort((a, b) => a._start - b._start || a._end - b._end);

    const rowsEnd = [];
    for (const it of segs) {
      let placed = false;
      for (let r = 0; r < rowsEnd.length; r++) {
        if (it._start > rowsEnd[r]) {
          it._row = r;
          rowsEnd[r] = it._end;
          placed = true;
          break;
        }
      }
      if (!placed) {
        it._row = rowsEnd.length;
        rowsEnd.push(it._end);
      }
    }
    return { segs, rowCount: rowsEnd.length };
  }

  function clearTimeline() {
    rows.innerHTML = "";
    hideTip();
  }

  function renderEmpty(message) {
    const empty = document.createElement("div");
    empty.className = "timeline-empty";
    empty.innerHTML = `<strong>Sin datos</strong><span>${message}</span>`;
    rows.appendChild(empty);
  }

  function renderLane(title, subtitle, items, mode, startYear) {
    const lane = document.createElement("div");
    lane.className = "timeline-lane";

    const laneTitle = document.createElement("div");
    laneTitle.className = "timeline-lane-title";
    laneTitle.innerHTML = `<strong>${title}</strong><small>${subtitle}</small>`;
    lane.appendChild(laneTitle);

    const barsWrap = document.createElement("div");
    barsWrap.className = "timeline-bars";
    lane.appendChild(barsWrap);

    const { segs, rowCount } = stackOverlaps(items, startYear);

    const neededH = Math.max(90, rowCount * (LANE_BAR_H + STACK_GAP) + 10);
    barsWrap.style.minHeight = `${neededH}px`;

    for (const it of segs) {
      const startX = 10 + it._start * MONTH_PX;
      const endX = 10 + (it._end + 1) * MONTH_PX;
      const w = Math.max(MONTH_PX, endX - startX - 2);

      const y = 6 + it._row * (LANE_BAR_H + STACK_GAP);

      const bar = document.createElement("div");
      bar.className = "timeline-bar";
      bar.style.left = `${startX}px`;
      bar.style.top = `${y}px`;
      bar.style.width = `${w}px`;
      bar.style.background = levelColor[it.nivel] || levelColor.otro;
      bar.setAttribute("tabindex", "0");
      bar.setAttribute("role", "button");

      const main = mode === "persona" ? `${it.label}` : `${it.persona}`;
      const sub = mode === "persona" ? `${it.institucion}` : `${it.label} · ${it.persona}`;

      bar.innerHTML = `
        <span class="bar-tag">${escapeHtml(it.nivel)}</span>
        <div class="bar-text">
          <b title="${escapeHtml(main)}">${escapeHtml(main)}</b>
          <span title="${escapeHtml(sub)}">${escapeHtml(sub)}</span>
        </div>
      `;

      const tooltipTitle = mode === "persona" ? `${it.label}` : `${it.persona}`;
      const tooltipSub = mode === "persona" ? `${it.institucion}` : `${it.label}`;
      const temas = Array.isArray(it.temas) ? it.temas : [];

      const handleShow = () => {
        showTip(bar, tooltipTitle, tooltipSub, it.nivel, it.inicio, it.fin, temas);
      };

      bar.addEventListener("mouseenter", handleShow);
      bar.addEventListener("mouseleave", hideTip);
      bar.addEventListener("focus", handleShow);
      bar.addEventListener("blur", hideTip);
      bar.addEventListener("click", (event) => {
        event.preventDefault();
        if (activeBar === bar && tooltip.classList.contains("show")) {
          hideTip();
          return;
        }
        handleShow();
      });
      bar.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleShow();
        }
      });

      barsWrap.appendChild(bar);
    }

    rows.appendChild(lane);
  }

  function buildTooltipContent(title, sub, nivel, inicio, fin, temas) {
    const topicsHtml = (temas && temas.length)
      ? `
        <div class="tooltip-topics">
          <div class="tooltip-topics-title">Temas</div>
          <div class="tooltip-meta">
            ${temas.map((tema) => `<span class="tooltip-pill">${escapeHtml(tema)}</span>`).join("")}
          </div>
        </div>
      `
      : `
        <div class="tooltip-topics">
          <div class="tooltip-topics-title">Temas</div>
          <div class="tooltip-empty">Sin temas vinculados</div>
        </div>
      `;

    return `
      <div class="tooltip-title">${escapeHtml(title)}</div>
      <div class="tooltip-subtitle">${escapeHtml(sub)}</div>
      <div class="tooltip-meta">
        <span class="tooltip-pill">${escapeHtml(nivel)}</span>
        <span class="tooltip-pill">${formatMY(inicio)} – ${formatMY(fin)}</span>
      </div>
      ${topicsHtml}
    `;
  }

  function scheduleTooltipPosition() {
    if (rafId) {
      return;
    }
    rafId = requestAnimationFrame(() => {
      rafId = null;
      updateTooltipPosition();
    });
  }

  function updateTooltipPosition() {
    if (!activeBar || !tooltip.classList.contains("show")) {
      return;
    }
    const panelRect = panel.getBoundingClientRect();
    const barRect = activeBar.getBoundingClientRect();

    if (
      barRect.right < panelRect.left ||
      barRect.left > panelRect.right ||
      barRect.bottom < panelRect.top ||
      barRect.top > panelRect.bottom
    ) {
      hideTip();
      return;
    }

    const padding = 12;
    const tooltipRect = tooltip.getBoundingClientRect();
    let left = barRect.left - panelRect.left + (barRect.width / 2) - (tooltipRect.width / 2);
    let top = barRect.top - panelRect.top - tooltipRect.height - 10;

    if (top < padding) {
      top = barRect.bottom - panelRect.top + 10;
    }

    left = clamp(left, padding, panelRect.width - tooltipRect.width - padding);
    top = clamp(top, padding, panelRect.height - tooltipRect.height - padding);

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function showTip(bar, title, sub, nivel, inicio, fin, temas) {
    activeBar = bar;
    tooltip.innerHTML = buildTooltipContent(title, sub, nivel, inicio, fin, temas);
    tooltip.classList.add("show");
    tooltip.setAttribute("aria-hidden", "false");
    scheduleTooltipPosition();
  }

  function hideTip() {
    tooltip.classList.remove("show");
    tooltip.setAttribute("aria-hidden", "true");
    activeBar = null;
  }

  function renderTimeline() {
    clearTimeline();

    const type = entityType.value;
    if (entitySelect.dataset.entityType !== type) {
      populateEntities(type);
    }
    const id = entitySelect.value;
    const list = type === "persona" ? PERSONAS : INSTITUCIONES;
    const selected = list.find((item) => String(item.id) === String(id));

    if (!selected) {
      headline.textContent = "Timeline";
      subhead.textContent = "Selecciona una entidad para ver cargos por periodo";
      renderEmpty("Selecciona una entidad para visualizar sus periodos.");
      currentStartYear = START_YEAR_DEFAULT;
      currentEndYear = END_YEAR_DEFAULT;
      buildGrid(currentStartYear, currentEndYear);
      return;
    }

    const selectedName = selected.nombre || "Sin nombre";
    headline.textContent = `Timeline · ${selectedName}`;
    if (type === "persona") {
      subhead.textContent = "Cargos ocupados (apilado cuando hay empalmes)";
    } else {
      subhead.textContent = "Personas y cargos por periodo dentro de la institución";
    }

    const items = selected.cargos || [];
    const { startYear, endYear } = getTimelineBounds(items);
    currentStartYear = startYear;
    currentEndYear = endYear;
    buildGrid(currentStartYear, currentEndYear);

    if (!items.length) {
      renderEmpty("Esta entidad todavía no tiene cargos con fechas completas.");
      return;
    }

    if (type === "persona") {
      renderLane("Cargos", "Barras = periodos de cargos · meses visibles", items, "persona", startYear);
    } else {
      renderLane(
        "Ocupación de cargos",
        "Barras = personas en el tiempo · apilado si se empalman",
        items,
        "institucion",
        startYear
      );
    }

    scrollNearYear(currentStartYear + 10, currentStartYear);
  }

  function scrollNearYear(year, startYear) {
    const idx = (year - startYear) * 12;
    const x = Math.max(0, idx * getMonthWidth() - 200);
    scroller.scrollLeft = x;
  }

  function scrollToToday() {
    const now = new Date();
    const idx = monthIndex(now, currentStartYear);
    const x = Math.max(0, idx * getMonthWidth() - 260);
    scroller.scrollLeft = x;
  }

  function populateEntities(type = entityType.value) {
    entitySelect.innerHTML = "";
    entitySelect.dataset.entityType = type;

    const list = type === "persona" ? PERSONAS : INSTITUCIONES;
    const sorted = [...list].sort((a, b) => (a.nombre || "").localeCompare(b.nombre || ""));

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Selecciona una opción";
    placeholder.disabled = true;
    placeholder.selected = true;
    entitySelect.appendChild(placeholder);

    sorted.forEach((item) => {
      const opt = document.createElement("option");
      opt.value = item.id;
      opt.textContent = item.nombre || "Sin nombre";
      entitySelect.appendChild(opt);
    });

    if (!sorted.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Sin resultados";
      entitySelect.appendChild(opt);
    }

    entitySelect.disabled = !sorted.length;
  }

  entityType.addEventListener("change", () => {
    populateEntities(entityType.value);
    renderTimeline();
  });

  entitySelect.addEventListener("change", renderTimeline);

  scroller.addEventListener("scroll", scheduleTooltipPosition);
  window.addEventListener("resize", scheduleTooltipPosition);

  document.addEventListener("pointerdown", (event) => {
    if (!tooltip.classList.contains("show")) {
      return;
    }
    const isBar = event.target.closest(".timeline-bar");
    if (!isBar) {
      hideTip();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideTip();
    }
  });

  populateEntities();
  renderTimeline();
})();
