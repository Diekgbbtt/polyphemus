import { Link } from "react-router-dom"
import { evalPaths } from "./EvalBreadcrumbs"
import type { EvalCoverage } from "./types"

export interface DonutSegment {
  label: string
  value: number
  to?: string
  note?: string
}

const RADIUS = 42
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

function percent(value: number, total: number): number {
  // A zero total is a real state, never a division by zero.
  return total > 0 ? Math.round((value / total) * 100) : 0
}

// A dependency-free SVG donut. The ring is decorative (`aria-hidden`); the
// legend carries the label, the count, the percentage and the total as text, so
// the chart never depends on color alone.
function Donut({
  title,
  centerValue,
  centerLabel,
  segments,
}: {
  title: string
  centerValue: number
  centerLabel: string
  segments: DonutSegment[]
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0)
  let offset = 0

  return (
    <figure className="eval-donut">
      <figcaption>{title}</figcaption>
      <div className="eval-donut-body">
        <svg
          className="eval-donut-svg"
          viewBox="0 0 100 100"
          role="presentation"
          aria-hidden="true"
          focusable="false"
        >
          <circle className="eval-donut-ring" cx="50" cy="50" r={RADIUS} />
          {segments.map((segment, index) => {
            const length = total > 0 ? (segment.value / total) * CIRCUMFERENCE : 0
            const circle = (
              <circle
                key={segment.label}
                className={`eval-donut-seg eval-donut-seg-${index}`}
                cx="50"
                cy="50"
                r={RADIUS}
                strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 50 50)"
              />
            )
            offset += length
            return circle
          })}
        </svg>
        <p className="eval-donut-center">
          <span className="eval-donut-value">{centerValue}</span>{" "}
          <span className="eval-donut-caption">{centerLabel}</span>
        </p>
      </div>
      <ul className="eval-donut-legend">
        {segments.map((segment, index) => (
          <li key={segment.label}>
            <span className={`eval-swatch eval-donut-seg-${index}`} aria-hidden="true" />
            {segment.to ? (
              <Link to={segment.to}>{segment.label}</Link>
            ) : (
              <span>{segment.label}</span>
            )}
            <span className="eval-legend-value">
              {segment.value} of {total} ({percent(segment.value, total)}%)
            </span>
            {segment.note && <span className="eval-legend-note">{segment.note}</span>}
          </li>
        ))}
      </ul>
    </figure>
  )
}

export function TargetCoverageDonut({ coverage }: { coverage: EvalCoverage }) {
  const { tested, with_identified, without_identified } = coverage.targets
  return (
    <Donut
      title="Target coverage"
      centerValue={tested}
      centerLabel="tested"
      segments={[
        { label: "With identified findings", value: with_identified },
        { label: "Without identified findings", value: without_identified },
      ]}
    />
  )
}

export function VulnerabilityCoverageDonut({ coverage }: { coverage: EvalCoverage }) {
  const { total, found, not_found, partial } = coverage.vulnerabilities
  return (
    <Donut
      title="Vulnerability coverage"
      centerValue={total}
      centerLabel="evaluated"
      segments={[
        { label: "Found", value: found, to: evalPaths.vulnerabilities },
        {
          label: "Not found",
          value: not_found,
          note:
            partial > 0
              ? `includes ${partial} partial`
              : "no partial verdicts in this set",
        },
      ]}
    />
  )
}
