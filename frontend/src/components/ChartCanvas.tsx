import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useRef } from "react";
import { downloadChartPng, downloadCsv } from "../lib/exports";
import { CHROME, compactNumber, fullNumber, seriesColor } from "../lib/palette";
import type { ChartSpec, ToolEnvelope } from "../lib/types";

/**
 * Renders a chart spec against rows the browser already holds.
 *
 * The model never sends data points -- it names a prior tool call and the
 * columns. This component looks that call up and plots its rows. There is no
 * step at which a number is retyped, so a chart cannot disagree with its query.
 */
export function ChartCanvas({
  spec,
  source,
}: {
  spec: ChartSpec;
  source: ToolEnvelope | undefined;
}) {
  const figureRef = useRef<HTMLElement>(null);

  if (!source) {
    return (
      <figure className="chart chart--broken">
        <figcaption>
          Chart references tool call <code>{spec.source_tool_call}</code>, which
          is not in this turn.
        </figcaption>
      </figure>
    );
  }

  const slug = spec.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 50);

  return (
    <figure className="chart" ref={figureRef}>
      <div className="chart__head">
        <figcaption className="chart__title">{spec.title}</figcaption>
        <div className="chart__actions">
          {spec.type !== "table" && (
            <button
              onClick={() => {
                const svg = figureRef.current?.querySelector("svg");
                if (svg) {
                  void downloadChartPng(
                    svg as SVGSVGElement,
                    `${slug}.png`,
                    CHROME.surfaceHex,
                  );
                }
              }}
              title="Download this chart as a PNG"
            >
              png
            </button>
          )}
          <button
            onClick={() => downloadCsv(source.rows, `${slug}.csv`)}
            title="Download the underlying rows as CSV"
          >
            csv
          </button>
        </div>
      </div>
      {spec.type === "table" ? (
        <ChartTable spec={spec} rows={source.rows} />
      ) : (
        <Plot spec={spec} rows={source.rows} />
      )}
      {/* The caption carries period and state set because a chart gets
          screenshotted into a deck without the text around it. */}
      <figcaption className="chart__caption">{spec.caption}</figcaption>
    </figure>
  );
}

type Row = Record<string, unknown>;

function Plot({ spec, rows }: { spec: ChartSpec; rows: Row[] }) {
  const { data, seriesKeys } = shape(spec, rows);
  const multi = seriesKeys.length > 1;

  const axis = {
    tick: { fill: CHROME.textMuted, fontSize: 11 },
    tickLine: false,
    axisLine: { stroke: CHROME.axis },
  };

  const common = (
    <>
      {/* Hairline, solid, horizontal only -- recessive by design. */}
      <CartesianGrid stroke={CHROME.grid} vertical={false} />
      <XAxis dataKey="__x" {...axis} interval="preserveStartEnd" />
      <YAxis {...axis} tickFormatter={compactNumber} width={56} />
      <Tooltip
        content={<ChartTooltip yLabel={spec.y} />}
        cursor={{ fill: "rgba(255,255,255,0.04)" }}
      />
      {/* A legend is the dependable identity channel whenever there is more
          than one series; a single series needs none -- the title says it. */}
      {multi && (
        <Legend
          wrapperStyle={{ fontSize: 11, color: CHROME.textMuted, paddingTop: 8 }}
          iconType="circle"
          iconSize={8}
        />
      )}
    </>
  );

  if (spec.type === "line") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          {common}
          {seriesKeys.map((key, i) => (
            <Line
              key={key}
              dataKey={key}
              stroke={seriesColor(i)}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={{ r: 4, fill: seriesColor(i), stroke: CHROME.surfaceHex, strokeWidth: 2 }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  const stacked = spec.type === "stacked_bar";
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        {common}
        {seriesKeys.map((key, i) => (
          <Bar
            key={key}
            dataKey={key}
            stackId={stacked ? "stack" : undefined}
            fill={seriesColor(i)}
            // Capped, not filling the band -- the leftover is air.
            maxBarSize={24}
            // Rounded at the data end, square on the baseline.
            radius={stacked ? 0 : [4, 4, 0, 0]}
            // The 2px surface gap between touching segments. Drawn as a stroke
            // in the surface colour because that is how SVG produces a gap --
            // it is separation, not a border added as extra ink.
            stroke={stacked ? CHROME.surfaceHex : undefined}
            strokeWidth={stacked ? 2 : 0}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Pivot rows into Recharts shape, splitting by `series` when asked. */
function shape(spec: ChartSpec, rows: Row[]): { data: Row[]; seriesKeys: string[] } {
  const x = spec.x;
  const y = spec.y;

  if (!spec.series) {
    return {
      data: rows.map((r) => ({ __x: String(r[x] ?? "—"), [y]: r[y] })),
      seriesKeys: [y],
    };
  }

  const buckets = new Map<string, Row>();
  const keys: string[] = [];
  for (const r of rows) {
    const xv = String(r[x] ?? "—");
    const sv = String(r[spec.series] ?? "—");
    if (!keys.includes(sv)) keys.push(sv);
    const bucket = buckets.get(xv) ?? { __x: xv };
    bucket[sv] = r[y];
    buckets.set(xv, bucket);
  }
  return { data: [...buckets.values()], seriesKeys: keys };
}

function ChartTooltip({
  active,
  payload,
  label,
  yLabel,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
  yLabel?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart__tooltip">
      <div className="chart__tooltip-label">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="chart__tooltip-row">
          <span className="chart__swatch" style={{ background: p.color }} />
          <span className="chart__tooltip-name">
            {p.name === yLabel ? yLabel : p.name}
          </span>
          <span className="chart__tooltip-value">
            {typeof p.value === "number" ? fullNumber(p.value) : String(p.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function ChartTable({ spec, rows }: { spec: ChartSpec; rows: Row[] }) {
  const columns = [spec.x, ...(spec.series ? [spec.series] : []), spec.y].filter(
    (c, i, a) => a.indexOf(c) === i,
  );
  const shown = rows.slice(0, 30);

  return (
    <div className="chart__table-wrap">
      <table className="chart__table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => {
                const v = r[c];
                const numeric = typeof v === "number";
                return (
                  <td key={c} className={numeric ? "is-number" : undefined}>
                    {v === null || v === undefined
                      ? "—"
                      : numeric
                        ? fullNumber(v)
                        : String(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && (
        <div className="chart__more">
          showing {shown.length} of {rows.length.toLocaleString()} rows
        </div>
      )}
    </div>
  );
}
