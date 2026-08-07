import { useQuery } from "@tanstack/react-query";
import { fetchCoverage } from "../lib/api";

/**
 * One line: what the data covers, and a way into the inspector.
 *
 * The original spelled out the sell-through caveat in full, permanently. For a
 * single expert user that is noise -- he knows. The caveat still travels where
 * it actually matters, which is on the chart captions, because a chart gets
 * screenshotted into a deck without any of the surrounding text. Here it lives
 * in the tooltip.
 *
 * The partial-year marker stays visible and stays coloured. That is the one
 * caveat capable of producing a wrong conclusion rather than an incomplete one.
 */
export function CoverageBanner({
  queryCount,
  inspectorOpen,
  onToggleInspector,
}: {
  queryCount: number;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
}) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["coverage"],
    queryFn: fetchCoverage,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  const toggle = (
    <button
      className="banner__toggle"
      onClick={onToggleInspector}
      aria-expanded={inspectorOpen}
      title={
        inspectorOpen
          ? "Hide the query inspector"
          : "Show the SQL behind every figure"
      }
    >
      <span>queries</span>
      {queryCount > 0 && <span className="banner__badge">{queryCount}</span>}
      <span className="banner__toggle-sign" aria-hidden="true">
        {inspectorOpen ? "−" : "+"}
      </span>
    </button>
  );

  if (isLoading || error || !data) {
    return (
      <header className="banner">
        <span className={error ? "banner__error" : "banner__value"}>
          {/* A coverage failure is worth saying out loud -- it means the
              backend is not answering, so nothing else will work either. */}
          {error ? "coverage unavailable" : "checking coverage…"}
        </span>
        <span className="banner__spacer" />
        {toggle}
      </header>
    );
  }

  const complete: number[] = [];
  for (let y = data.period_start; y <= data.period_end; y++) {
    if (!data.partial_periods.includes(y)) complete.push(y);
  }

  return (
    <header className="banner">
      <span className="banner__value mono" title={data.notes.join("\n\n")}>
        {complete.join(", ")}
        {data.partial_periods.length > 0 && (
          <>
            {complete.length > 0 && " · "}
            <span className="banner__partial" title={data.caveats.join("\n\n")}>
              {data.partial_periods.join(", ")} partial
            </span>
          </>
        )}
        <span className="banner__sep"> · </span>
        <span title={data.states.join(", ")}>{data.state_count} states</span>
      </span>

      <span className="banner__spacer" />
      {toggle}
    </header>
  );
}
