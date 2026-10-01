// The eval orchestrator's monitor tool (#289).
//
// The custom tool offered to the `eval-orchestrator` agent. One call is one
// tick of the post-execution workflow control plane: it shells to
// `python3 -m orchestrator monitor <setup>` (`PYTHONPATH=eval`), which sweeps
// every trial record under the runs root, verifies each trial's execution
// state, and advances one node - a successful execution dispatches the
// assessment subagent; a present `verdicts.yaml` dispatches the diagnoser for
// its `missed`/`partial` verdicts; a present, paired `diagnoses.yaml` completes
// the trial. The tool is the only way the agent advances the chain; the
// workflow that calls it is `eval/prompts/orchestrator.md`.
//
// The plugin is auto-discovered from `.opencode/plugin/`; `.opencode/opencode.json`
// also names it explicitly in the `plugin` section.

import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"

export const EvalMonitor: Plugin = async ({ $, directory }) => {
  return {
    tool: {
      eval_monitor: tool({
        description:
          "One tick of the eval harness post-execution workflow control plane. " +
          "Sweeps every trial record under the runs root, verifies each trial's " +
          "execution state, and advances one node: a successful execution " +
          "dispatches the assessment subagent; a present verdicts.yaml dispatches " +
          "the diagnoser for its missed/partial verdicts; a present, paired " +
          "diagnoses.yaml completes the trial. A failed, blocked, or timed-out " +
          "execution is deferred (the surfer owns recovery). Returns the per-trial " +
          "state report; exit 1 means at least one node escalated.",
        args: {
          setup: tool.schema.string().describe("path to the EvalSetup YAML"),
          runs_root: tool.schema
            .string()
            .optional()
            .describe("where per-trial record directories live"),
          data_root: tool.schema
            .string()
            .optional()
            .describe("the instance's app data root"),
          ground_truth: tool.schema
            .string()
            .optional()
            .describe("the challenge ground-truth directory"),
          command: tool.schema
            .string()
            .optional()
            .describe("the assessment agent command line ({prompt} {trial_record} {ground_truth} {data_root} {destination} {trace_id})"),
          diagnose_command: tool.schema
            .string()
            .optional()
            .describe("the diagnoser agent command line ({prompt} {trial_record} {verdicts} {ground_truth} {data_root} {destination} {vulns} {trace_id})"),
          repo: tool.schema.string().optional().describe("the canonical eval checkout"),
          instances_root: tool.schema
            .string()
            .optional()
            .describe("where per-instance worktrees live"),
          branch: tool.schema.string().optional().describe("the read-only eval branch"),
          state: tool.schema
            .string()
            .optional()
            .describe("the alignment state file"),
          budget_s: tool.schema
            .number()
            .optional()
            .describe("seconds a dispatched node waits before it re-dispatches or escalates"),
          dry_run: tool.schema
            .boolean()
            .optional()
            .describe("report each trial's tick state without dispatching anything"),
        },
        async execute(args) {
          const argv: string[] = [
            "python3",
            "-m",
            "orchestrator",
            "monitor",
            args.setup,
          ]
          const flag = (name: string, value?: string) => {
            if (value !== undefined && value !== "") argv.push(name, value)
          }
          flag("--runs-root", args.runs_root)
          flag("--data-root", args.data_root)
          flag("--ground-truth", args.ground_truth)
          flag("--command", args.command)
          flag("--diagnose-command", args.diagnose_command)
          flag("--repo", args.repo)
          flag("--instances-root", args.instances_root)
          flag("--branch", args.branch)
          flag("--state", args.state)
          if (args.budget_s !== undefined) argv.push("--budget-s", String(args.budget_s))
          if (args.dry_run) argv.push("--dry-run")

          const result = await $`${argv}`
            .cwd(directory)
            .env({ ...process.env, PYTHONPATH: "eval" })
            .nothrow()
            .quiet()
          return {
            title: `eval_monitor ${args.setup}`,
            output: result.stdout.toString() + result.stderr.toString(),
            metadata: { exitCode: result.exitCode, argv },
          }
        },
      }),
    },
  }
}
