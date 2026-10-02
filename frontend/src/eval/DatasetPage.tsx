import { Link, useParams } from "react-router-dom"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"

// One benchmark dataset and its Target ("machine") roster.
export function DatasetPage() {
  const { datasetId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const { dataset, targets } = snapshot
  const crumbs = [{ label: "Eval", to: evalPaths.dashboard }, { label: dataset.name }]
  if (datasetId !== dataset.id) {
    return (
      <div className="eval-page">
        <EvalBreadcrumbs items={crumbs} />
        <p className="eval-empty">Unknown dataset “{datasetId}”.</p>
      </div>
    )
  }

  return (
    <div className="eval-page">
      <EvalBreadcrumbs items={crumbs} />
      <header className="eval-header">
        <h1>{dataset.name}</h1>
        <p className="eval-dataset-id">{dataset.id}</p>
      </header>

      <section aria-label="Targets (machines)">
        <h2>Targets (machines)</h2>
        {targets.length === 0 ? (
          <p className="eval-empty">No target machines recorded.</p>
        ) : (
          <table className="eval-table">
            <thead>
              <tr>
                <th scope="col">Target (machine)</th>
                <th scope="col">Trials</th>
                <th scope="col">Identified</th>
                <th scope="col">Partial</th>
                <th scope="col">Missed</th>
              </tr>
            </thead>
            <tbody>
              {targets.map((target) => (
                <tr key={target.target_id}>
                  <th scope="row">
                    <Link to={evalPaths.target(target.target_id)}>{target.target_id}</Link>
                  </th>
                  <td>{target.trial_count}</td>
                  <td>{target.identified_count}</td>
                  <td>{target.partial_count}</td>
                  <td>{target.missed_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
