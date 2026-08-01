import { useQuery } from "@tanstack/react-query";
import { fetchCoverage } from "../lib/api";

/**
 * Always on screen, per spec. Its job is to make it impossible to forget what
 * the data actually covers -- and specifically that 2026 is partial, which is
 * the caveat most likely to produce a wrong conclusion.
 */
export function CoverageBanner() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["coverage"],
    queryFn: fetchCoverage,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <header className="banner">
        <span className="banner__label">Coverage</span>
        <span className="banner__value">checking…</span>
      </header>
    );
  }

  if (error || !data) {
    return (
      <header className="banner">
        <span className="banner__label">Coverage</span>
        <span className="banner__error">
          unavailable — {error instanceof Error ? error.message : "unknown error"}
        </span>
      </header>
    );
  }

  const complete = [];
  for (let y = data.period_start; y <= data.period_end; y++) {
    if (!data.partial_periods.includes(y)) complete.push(y);
  }

  return (
    <header className="banner">
      <span className="banner__label">Coverage</span>

      <span className="banner__value mono">
        {complete.join(", ")}
        {data.partial_periods.length > 0 && (
          <>
            {complete.length > 0 && ", "}
            <span
              className="banner__partial"
              title={data.caveats.join("\n\n")}
            >
              {data.partial_periods.join(", ")} partial
            </span>
          </>
        )}
      </span>

      <span className="banner__label">States</span>
      <span className="banner__value mono" title={data.states.join(", ")}>
        {data.state_count}
      </span>

      <span className="banner__spacer" />

      <span className="banner__label" title={data.notes.join("\n\n")}>
        BDSA retail sell-through · covered states only · not total market
      </span>
    </header>
  );
}
