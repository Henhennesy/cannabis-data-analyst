/** Getting data out: CSV of the underlying rows, PNG of a chart. */

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * CSV of the FULL row set, not the truncated view on screen.
 *
 * Values are written at full precision. The interface compacts numbers for
 * legibility ($3.87B), but a compacted number in an export would be a
 * different number, and this file is what gets pasted into a model.
 */
export function downloadCsv(rows: Record<string, unknown>[], filename: string): void {
  if (rows.length === 0) return;
  const columns = Object.keys(rows[0]);

  const cell = (v: unknown): string => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    // Excel treats a leading =, +, - or @ as a formula. Prefix with a quote so
    // a brand called "-Foo" cannot execute as one.
    const safe = /^[=+\-@]/.test(s) ? `'${s}` : s;
    return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
  };

  const lines = [
    columns.join(","),
    ...rows.map((r) => columns.map((c) => cell(r[c])).join(",")),
  ];
  // BOM so Excel reads UTF-8 rather than mangling non-ASCII brand names.
  download(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }), filename);
}

/**
 * PNG of a chart, rendered from its live SVG.
 *
 * Serialising the SVG loses the stylesheet, because the marks reference CSS
 * custom properties that only resolve against the document. Every computed
 * paint value is therefore inlined onto its element first, and the background
 * is painted explicitly -- a transparent PNG dropped on a white slide would
 * render this dark-theme chart unreadable.
 */
export async function downloadChartPng(
  svg: SVGSVGElement,
  filename: string,
  background: string,
  scale = 2,
): Promise<void> {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  inlineComputedPaint(svg, clone);

  const width = svg.clientWidth || Number(svg.getAttribute("width")) || 800;
  const height = svg.clientHeight || Number(svg.getAttribute("height")) || 400;
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");

  const source = new XMLSerializer().serializeToString(clone);
  const svgBlob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);

  try {
    const img = await loadImage(url);
    const canvas = document.createElement("canvas");
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, "image/png"));
    if (blob) download(blob, filename);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Copy resolved fill/stroke/font from the live tree onto the detached clone. */
function inlineComputedPaint(live: Element, clone: Element): void {
  const computed = getComputedStyle(live);
  const el = clone as SVGElement & { style: CSSStyleDeclaration };
  for (const prop of [
    "fill", "stroke", "stroke-width", "opacity", "fill-opacity", "stroke-opacity",
    "font-family", "font-size", "font-weight", "text-anchor",
  ]) {
    const value = computed.getPropertyValue(prop);
    if (value) el.style.setProperty(prop, value);
  }
  const liveKids = live.children;
  const cloneKids = clone.children;
  for (let i = 0; i < liveKids.length && i < cloneKids.length; i++) {
    inlineComputedPaint(liveKids[i], cloneKids[i]);
  }
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}
