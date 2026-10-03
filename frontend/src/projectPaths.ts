// The project workspace's canonical links. Every identifier is URL-encoded on
// its own: they are stable ids, never display strings.
const enc = encodeURIComponent

export const projectPaths = {
  live: (projectId: string) => `/p/${enc(projectId)}`,
  runs: (projectId: string) => `/p/${enc(projectId)}/runs`,
  evals: (projectId: string) => `/p/${enc(projectId)}/evals`,
  trial: (projectId: string, targetId: string, targetRunId: string, trialId: string) =>
    `${projectPaths.evals(projectId)}/${enc(targetId)}/${enc(targetRunId)}/${enc(trialId)}`,
  // Reserved for the artifact routes (Tasks 9-10); the routes are not
  // registered yet, so nothing links here in this task.
  artifacts: (
    projectId: string,
    targetId: string,
    targetRunId: string,
    trialId: string,
  ) => `${projectPaths.trial(projectId, targetId, targetRunId, trialId)}/artifacts`,
  artifact: (
    projectId: string,
    targetId: string,
    targetRunId: string,
    trialId: string,
    artifactId: string,
  ) => `${projectPaths.artifacts(projectId, targetId, targetRunId, trialId)}/${enc(artifactId)}`,
}
