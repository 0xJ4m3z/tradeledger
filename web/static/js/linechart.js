// Minimal, dependency-free SVG line chart.
//
// Renders into every element with a [data-chart-points] attribute holding a
// JSON array of {date, value} objects (already computed server-side by
// web/charts.py from the same pure functions the desktop app's matplotlib
// chart uses — see app/services/pnl_series.py).
//
// Deliberately plain SVG (not <canvas>) so chart points are real DOM nodes —
// inspectable by Playwright via data-testid, not just pixels.
(function () {
  const GREEN = "#3fb950";
  const RED = "#f85149";
  const MUTED = "#8b949e";

  function fmtUsd(v) {
    const sign = v < 0 ? "-" : "";
    return `${sign}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function renderChart(container) {
    let points;
    try {
      points = JSON.parse(container.dataset.chartPoints || "[]");
    } catch (e) {
      points = [];
    }

    container.innerHTML = "";

    if (!points.length) {
      const empty = document.createElement("div");
      empty.className = "chart-empty";
      empty.dataset.testid = "chart-empty";
      empty.textContent = "No data to chart yet.";
      container.appendChild(empty);
      return;
    }

    const width = container.clientWidth || 800;
    const height = 260;
    const padL = 56, padR = 16, padT = 16, padB = 28;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    const values = points.map((p) => p.value);
    let minV = Math.min(0, ...values);
    let maxV = Math.max(0, ...values);
    if (minV === maxV) { minV -= 1; maxV += 1; }

    const finalValue = values[values.length - 1];
    const color = finalValue >= 0 ? GREEN : RED;

    const xAt = (i) => points.length === 1 ? padL + plotW / 2 : padL + (i / (points.length - 1)) * plotW;
    const yAt = (v) => padT + plotH - ((v - minV) / (maxV - minV)) * plotH;

    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("data-testid", "line-chart-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Chart from ${points[0].date} to ${points[points.length - 1].date}, ending at ${fmtUsd(finalValue)}`);

    // Zero line
    const zeroY = yAt(0);
    const zeroLine = document.createElementNS(svgNS, "line");
    zeroLine.setAttribute("x1", padL);
    zeroLine.setAttribute("x2", width - padR);
    zeroLine.setAttribute("y1", zeroY);
    zeroLine.setAttribute("y2", zeroY);
    zeroLine.setAttribute("stroke", MUTED);
    zeroLine.setAttribute("stroke-dasharray", "3,3");
    zeroLine.setAttribute("stroke-width", "1");
    svg.appendChild(zeroLine);

    // Line + fill path
    const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${xAt(i)} ${yAt(p.value)}`).join(" ");
    const fillPath = `${linePath} L ${xAt(points.length - 1)} ${zeroY} L ${xAt(0)} ${zeroY} Z`;

    const fill = document.createElementNS(svgNS, "path");
    fill.setAttribute("d", fillPath);
    fill.setAttribute("fill", color);
    fill.setAttribute("fill-opacity", "0.12");
    fill.setAttribute("stroke", "none");
    svg.appendChild(fill);

    const line = document.createElementNS(svgNS, "path");
    line.setAttribute("d", linePath);
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", color);
    line.setAttribute("stroke-width", "2");
    line.setAttribute("data-testid", "line-chart-path");
    svg.appendChild(line);

    // Point markers (also carry data for Playwright assertions)
    points.forEach((p, i) => {
      const c = document.createElementNS(svgNS, "circle");
      c.setAttribute("cx", xAt(i));
      c.setAttribute("cy", yAt(p.value));
      c.setAttribute("r", points.length > 60 ? 0 : 3);
      c.setAttribute("fill", color);
      c.setAttribute("data-testid", "chart-point");
      c.setAttribute("data-date", p.date);
      c.setAttribute("data-value", p.value);
      svg.appendChild(c);
    });

    // X-axis end labels
    [points[0], points[points.length - 1]].forEach((p, idx) => {
      const t = document.createElementNS(svgNS, "text");
      t.setAttribute("x", idx === 0 ? padL : width - padR);
      t.setAttribute("y", height - 8);
      t.setAttribute("fill", MUTED);
      t.setAttribute("font-size", "11");
      t.setAttribute("text-anchor", idx === 0 ? "start" : "end");
      t.textContent = p.date.slice(0, 10);
      svg.appendChild(t);
    });

    // Y-axis end labels
    [minV, maxV].forEach((v) => {
      const t = document.createElementNS(svgNS, "text");
      t.setAttribute("x", 8);
      t.setAttribute("y", yAt(v) + 4);
      t.setAttribute("fill", MUTED);
      t.setAttribute("font-size", "11");
      t.textContent = fmtUsd(v);
      svg.appendChild(t);
    });

    container.appendChild(svg);

    // Hover crosshair + tooltip
    const tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    tooltip.dataset.testid = "chart-tooltip";
    tooltip.style.cssText = "position:absolute; display:none; background:#0d1117; border:1px solid #30363d; border-radius:4px; padding:6px 10px; font-size:12px; pointer-events:none; color:#c9d1d9;";
    container.style.position = "relative";
    container.appendChild(tooltip);

    svg.addEventListener("mousemove", (evt) => {
      const rect = svg.getBoundingClientRect();
      const relX = ((evt.clientX - rect.left) / rect.width) * width;
      let nearest = 0;
      let best = Infinity;
      points.forEach((p, i) => {
        const d = Math.abs(xAt(i) - relX);
        if (d < best) { best = d; nearest = i; }
      });
      const p = points[nearest];
      tooltip.style.display = "block";
      tooltip.style.left = `${(xAt(nearest) / width) * 100}%`;
      tooltip.style.top = "8px";
      tooltip.textContent = `${p.date.slice(0, 10)} — ${fmtUsd(p.value)}`;
      tooltip.dataset.date = p.date;
      tooltip.dataset.value = p.value;
    });
    svg.addEventListener("mouseleave", () => { tooltip.style.display = "none"; });
  }

  function renderAll() {
    document.querySelectorAll("[data-chart-points]").forEach(renderChart);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAll);
  } else {
    renderAll();
  }
})();
