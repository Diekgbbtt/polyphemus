import { Link } from "react-router-dom"

export interface Crumb {
  label: string
  to?: string
}

// The eval section's canonical links. Every id is URL-encoded: it is a stable
// identifier, not a display string.
const enc = encodeURIComponent
export const evalPaths = {
  dashboard: "/eval",
  dataset: (dataset_id: string) => `/eval/datasets/${enc(dataset_id)}`,
  target: (target_id: string) => `/eval/targets/${enc(target_id)}`,
  trial: (target_id: string, target_run_id: string, trial_id: string) =>
    `/eval/trials/${enc(target_id)}/${enc(target_run_id)}/${enc(trial_id)}`,
  trialArtifact: (
    target_id: string,
    target_run_id: string,
    trial_id: string,
    artifact: string,
  ) => `/eval/trials/${enc(target_id)}/${enc(target_run_id)}/${enc(trial_id)}/${artifact}`,
  version: (eval_sha: string, stack_fingerprint: string) =>
    `/eval/versions/${enc(eval_sha)}/${enc(stack_fingerprint)}`,
  vulnerabilities: "/eval/vulnerabilities",
}

// The trail for one eval page. The last crumb is the current page: never a
// link, always marked `aria-current="page"`.
export function EvalBreadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="eval-crumbs" aria-label="Breadcrumb">
      <ol>
        {items.map((item, index) => {
          const current = index === items.length - 1
          return (
            <li key={`${item.label}-${index}`}>
              {item.to && !current ? (
                <Link to={item.to}>{item.label}</Link>
              ) : (
                <span aria-current={current ? "page" : undefined}>{item.label}</span>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
