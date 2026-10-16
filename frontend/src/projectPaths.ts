// The project workspace's canonical links. Every identifier is URL-encoded on
// its own: they are stable ids, never display strings.
const enc = encodeURIComponent

export const projectPaths = {
  live: (projectId: string) => `/p/${enc(projectId)}`,
  runs: (projectId: string) => `/p/${enc(projectId)}/runs`,
  evals: (projectId: string) => `/p/${enc(projectId)}/evals`,
  // One file of the project's own artifact tree - the project-scoped sibling of
  // the Trial artifact routes, with no Trial in the path.
  projectArtifact: (projectId: string, artifactId: string) =>
    `/p/${enc(projectId)}/artifacts/${enc(artifactId)}`,
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

// The canonical Target -> Trial routes. The Target is the primary entity; a
// Trial is identified by its full (target, run, trial) identity, never by the
// internal project id it happens to share.
export const targetPaths = {
  target: (targetId: string) => `/targets/${enc(targetId)}`,
  trial: (targetId: string, targetRunId: string, trialId: string) =>
    `/targets/${enc(targetId)}/trials/${enc(targetRunId)}/${enc(trialId)}`,
  trialArtifact: (
    targetId: string,
    targetRunId: string,
    trialId: string,
    artifactId: string,
  ) =>
    `${targetPaths.trial(targetId, targetRunId, trialId)}/artifacts/${enc(artifactId)}`,
}
