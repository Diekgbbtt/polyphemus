import { Link, useParams } from "react-router-dom"
import { getAppState, getProjectSettings, getProjectUsage, getProjects } from "../api/client"
import type { Project, ProjectSettings, ProjectUsage } from "../api/types"
import { ProjectArtifactsBlock } from "../eval/ProjectArtifactsBlock"
import { isValidProjectUsage } from "../eval/ProjectUsageSummary"
import { GraphView } from "../graph/GraphView"
import { useGraphData } from "../graph/useGraphData"
import { RUN_KINDS, activeRuns } from "../projectRuns"
import { usePolledResource } from "../usePolledResource"
import type { PolledResource } from "../usePolledResource"
import { ProjectNav } from "./ProjectNav"

// The live board's cadence: the in-flight runs are the one thing worth watching
// move while you sit on this page.
const RUNS_POLL_MS = 2500

// One project, for itself: its identity, its live graph, its in-flight runs and
// its cumulative token spend.
//
// This is deliberately NOT a Target/Trial view. A project with no Trial is not
// attributed to any Target, and every block below reads only what is keyed by
// `project_id` - so the page shows what the platform holds for the project
// itself and never fabricates a Trial result.
export function GraphPage() {
  const { projectId = "" } = useParams()
  const graph = useGraphData(projectId)

  const projects = usePolledResource<Project[]>({
    key: "projects",
    load: (signal) => getProjects(signal),
  })
  const project = projects.data?.find((item) => item.project_id === projectId) ?? null

  const appState = usePolledResource({
    key: "app-state",
    load: (signal) => getAppState(signal),
    intervalMs: RUNS_POLL_MS,
  })
  // The body is rendered as received: a source that answers with something else
  // leaves the block empty instead of throwing.
  const state =
    appState.data?.projects?.find((item) => item.project_id === projectId) ?? null
  const anyRun = state !== null && RUN_KINDS.some((kind) => activeRuns(state, kind).length > 0)

  const usage = usePolledResource<ProjectUsage>({
    key: `usage:${projectId}`,
    load: async (signal) => {
      const body = (await getProjectUsage(projectId, signal)) as unknown
      // A body that does not carry the contract is a failure, never a zero.
      if (!isValidProjectUsage(body)) throw new Error("invalid usage body")
      return body
    },
  })

  const settings = usePolledResource<ProjectSettings>({
    key: `settings:${projectId}`,
    load: async (signal) => {
      const body = (await getProjectSettings(projectId, signal)) as unknown
      // A body without the contract is a failure, never an empty configuration.
      if (!isPlainObject(body) || !isPlainObject(body.recon)) {
        throw new Error("invalid settings body")
      }
      return { recon: body.recon }
    },
  })

  return (
    <main className="project-page">
      <header className="project-page-header">
        <ProjectNav projectId={projectId} active="graph" />
        <p className="project-page-back">
          <Link to="/">← All targets</Link>
        </p>
        <h1 className="project-page-title">{project?.name ?? projectId}</h1>
        <p className="project-page-id">{projectId}</p>
        <p className="project-page-note">
          Project-scoped view: the graph, the runs and the token counters below
          are what the platform holds for this project itself. A project with no
          Trial is not attributed to a Target, so nothing here is a Target result.
        </p>
      </header>

      <section className="project-block" aria-label="Project details">
        <h2 className="project-block-title">Project</h2>
        {projects.loading && project === null ? (
          <p className="project-block-muted">Loading project…</p>
        ) : (
          <dl className="project-facts">
            <div>
              <dt>Project id</dt>
              <dd className="project-fact-mono">{projectId}</dd>
            </div>
            <div>
              <dt>Name</dt>
              <dd>{project?.name ?? "Unavailable"}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{project?.created_at ?? "Unavailable"}</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="project-block" aria-label="Project settings">
        <h2 className="project-block-title">Configuration</h2>
        <p className="project-block-note">
          The recon settings stored for this project — the operator's own blob,
          read-only. It carries no auth.
        </p>
        <SettingsBody settings={settings} />
      </section>

      <section className="project-block" aria-label="Active runs">
        <h2 className="project-block-title">Active runs</h2>
        {appState.loading && state === null ? (
          <p className="project-block-muted">Loading runs…</p>
        ) : (
          <>
            {RUN_KINDS.map((kind) => {
              const runs = state ? activeRuns(state, kind) : []
              if (runs.length === 0) return null
              return (
                <section
                  key={kind}
                  className={`live-run-group live-run-group--${kind}`}
                  aria-label={`${kind} runs`}
                >
                  <h3 className="live-run-group-title">{kind}</h3>
                  <ul className="live-run-list">
                    {runs.map((run) => (
                      <li key={run.id} className="live-run">
                        <span className="live-run-id">{run.id}</span>
                        <span className="live-run-status">{run.status}</span>
                        {run.phase !== null && (
                          <span className="live-run-phase">phase {run.phase}</span>
                        )}
                        {run.liveness !== null && (
                          <span className="live-run-liveness" data-liveness={run.liveness}>
                            {run.liveness}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )
            })}
            {!anyRun && <p className="project-block-muted">No runs in flight.</p>}
          </>
        )}
      </section>

      <section className="project-block" aria-label="Project graph">
        <h2 className="project-block-title">Graph</h2>
        {graph.notFound ? (
          <p className="project-block-muted">No graph is stored for this project.</p>
        ) : (
          <GraphView
            data={graph.data}
            loading={graph.loading}
            error={graph.error}
            label="Live project graph"
          />
        )}
      </section>

      <section className="project-block" aria-label="Project artifacts">
        <h2 className="project-block-title">Artifacts</h2>
        <p className="project-block-note">
          The Hunting and Skill files this project's own data root holds, read
          with no Trial in the path.
        </p>
        <ProjectArtifactsBlock projectId={projectId} />
      </section>

      <section className="project-block" aria-label="Token usage">
        <h2 className="project-block-title">Token usage</h2>
        <p className="project-block-note">
          Cumulative tokens for this project since the backend started — they are
          not a Trial's spend.
        </p>
        <UsageBody usage={usage} />
      </section>
    </main>
  )
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

// One setting's value as text: scalars as they are, anything structured as
// compact JSON, so nothing is silently dropped from the blob.
function formatSetting(value: unknown): string {
  if (value === null) return "null"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

// The project's stored recon settings, read-only. An empty blob is stated as
// such; a failed refresh keeps the last one and says it may be out of date.
function SettingsBody({ settings }: { settings: PolledResource<ProjectSettings> }) {
  if (settings.data) {
    const entries = Object.entries(settings.data.recon).sort(([a], [b]) =>
      a.localeCompare(b),
    )
    if (entries.length === 0) {
      return (
        <p className="project-block-muted">No settings are stored for this project.</p>
      )
    }
    return (
      <>
        {settings.error !== null && (
          <p className="project-block-muted">
            Settings not up to date — showing the last reading.
          </p>
        )}
        <dl className="project-facts">
          {entries.map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{formatSetting(value)}</dd>
            </div>
          ))}
        </dl>
      </>
    )
  }
  if (settings.error !== null) {
    return <p className="project-block-muted">Settings unavailable.</p>
  }
  return <p className="project-block-muted">Loading settings…</p>
}

// The project's cumulative counters. The last reading survives a failed refresh
// (stated as stale); a first read that never succeeded is unavailable, which is
// never rendered as zero.
function UsageBody({ usage }: { usage: PolledResource<ProjectUsage> }) {
  if (usage.data) {
    const tokens = usage.data
    return (
      <>
        <dl className="live-usage-stats">
          <div>
            <dt>Total tokens</dt>
            <dd data-usage="total">{tokens.total_tokens}</dd>
          </div>
          <div>
            <dt>Cached input</dt>
            <dd data-usage="cached">{tokens.context_tokens.cached}</dd>
          </div>
          <div>
            <dt>Uncached input</dt>
            <dd data-usage="uncached">{tokens.context_tokens.uncached}</dd>
          </div>
          <div>
            <dt>Reasoning output</dt>
            <dd data-usage="reasoning">{tokens.generated_tokens.reasoning}</dd>
          </div>
          <div>
            <dt>Visible output</dt>
            <dd data-usage="visible">{tokens.generated_tokens.visible}</dd>
          </div>
          <div>
            <dt>Calls</dt>
            <dd data-usage="calls">{tokens.calls}</dd>
          </div>
        </dl>
        {usage.error !== null && (
          <p className="live-usage-stale">
            Usage not up to date — showing the last reading.
          </p>
        )}
      </>
    )
  }
  if (usage.error !== null) {
    return <p className="live-usage-error">Usage unavailable.</p>
  }
  return <p className="live-usage-loading">Loading project usage…</p>
}
