import { Link } from "react-router-dom"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"

function matchLabel(unit: string | null, faultClass: string | null, symptom: string | null) {
  return [unit ?? "—", faultClass ?? "—", symptom ?? "—"].join(" · ")
}

// Every successfully identified vulnerability. `successes` is identified-only
// by contract: partial and missed never appear here.
export function SuccessfulVulnerabilitiesPage() {
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const { successes, dataset } = snapshot

  return (
    <div className="eval-page">
      <EvalBreadcrumbs
        items={[
          { label: "Eval", to: evalPaths.dashboard },
          { label: dataset.name, to: evalPaths.dataset(dataset.id) },
          { label: "Successful vulnerabilities" },
        ]}
      />
      <header className="eval-header">
        <h1>Successfully identified vulnerabilities</h1>
        <p className="eval-dataset-id">{dataset.name}</p>
      </header>

      {successes.length === 0 ? (
        <p className="eval-empty">No vulnerabilities were identified.</p>
      ) : (
        <table className="eval-table">
          <thead>
            <tr>
              <th scope="col">Vulnerability</th>
              <th scope="col">Target (machine)</th>
              <th scope="col">Trial</th>
              <th scope="col">Version</th>
              <th scope="col">Confidence</th>
              <th scope="col">Match (unit · fault class · symptom)</th>
            </tr>
          </thead>
          <tbody>
            {successes.map((row) => (
              <tr key={`${row.target_id}/${row.target_run_id}/${row.trial_id}/${row.vuln_id}`}>
                <th scope="row">{row.vuln_id}</th>
                <td>
                  <Link to={evalPaths.target(row.target_id)}>{row.target_id}</Link>
                </td>
                <td>
                  <Link to={evalPaths.trial(row.target_id, row.target_run_id, row.trial_id)}>
                    {row.trial_id}
                  </Link>
                </td>
                <td>
                  <Link to={evalPaths.version(row.eval_sha, row.stack_fingerprint)}>
                    <span className="eval-ref">{row.eval_sha}</span> ·{" "}
                    <span className="eval-ref">{row.stack_fingerprint}</span>
                  </Link>
                </td>
                <td>{Math.round(row.confidence * 100)}%</td>
                <td>{matchLabel(row.matched.unit, row.matched.fault_class, row.matched.symptom)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
