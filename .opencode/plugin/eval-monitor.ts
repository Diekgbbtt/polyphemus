// The eval orchestrator's harness tools (#289, #350).
//
// The custom tools offered to the `eval-orchestrator` agent:
//
// - `next_target` advances the multi-target chain (reclaim the previous image,
//   pull the next, bring it up, health-check it) by shelling the CLI verb.
// - `eval_monitor` drives the post-execution workflow. It is no longer a
//   detached `opencode run`: the symbolic Python layer (`orchestrator monitor`,
//   PYTHONPATH=eval) is a pure plan engine and the plugin performs each
//   `dispatch` action as a NATIVE, AWAITED opencode child session using the SDK
//   client the runtime injects. The child is bounded by a wall-clock timeout
//   and aborted on expiry, so a fatal provider error yields a NON-zero terminal
//   (never a hang), and the assessor -> diagnoser transition is fully
//   synchronous within the one tool call.
//
// The plan/apply loop:
//   1. `monitor --plan` returns JSON: per-trial state plus the dispatch actions.
//   2. For each dispatch action the plugin runs the role agent as a child
//      session, then classifies its terminal (success / no-output / failure /
//      timeout / provider).
//   3. `monitor --results <file>` applies those terminals to the trial records
//      and returns the next plan; the loop repeats until nothing is pending.
// No `opencode run`, no detached process, no discarded handle.
//
// The plugin is auto-discovered from `.opencode/plugin/`; `.opencode/opencode.json`
// also names it explicitly in the `plugin` section.

import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"
import { existsSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

// The most plan/apply rounds in one tool call: assessment then diagnosis, with
// headroom for a single-node retry. A node that fails backs off to a later tick,
// so the loop converges well before this bound.
const MAX_APPLY_ROUNDS = 8

// A dispatch action is dispatched (not escalated) when its action is this.
// The plugin reads the action vocabulary from the Python plan, so only the
// dispatch needs naming here.
const ACTION_DISPATCH = "dispatch"

const RESULT_SUCCESS = "success"
const RESULT_FAILURE = "failure"
const RESULT_NO_OUTPUT = "no-output"
const RESULT_TIMEOUT = "timeout"

// Serialize an unknown error-ish value to a string that keeps its message.
// A plain API error body JSON-stringifies; an Error (or any non-plain object)
// is rendered as `${name}: ${message}` because `JSON.stringify(new Error(x))`
// is "{}" and would hide the provider-quota phrase the 5h backoff keys on.
const serializeError = (value: unknown): string => {
  if (value === null || value === undefined) return ""
  if (typeof value === "string") return value
  if (value instanceof Error) return `${value.name}: ${value.message}`
  try {
    const json = JSON.stringify(value)
    return json === undefined || json === "{}" ? String(value) : json
  } catch {
    return String(value)
  }
}

export const EvalMonitor: Plugin = async ({ $, directory, client }) => {
  // The live child session per trial record, so a re-dispatch aborts the prior
  // child before it starts a new one (the native analogue of killing a leaked
  // process group). Cleared when the child reaches a terminal.
  const activeChildren = new Map<string, string>()

  const runCli = async (argv: string[]) => {
    const result = await $`${argv}`
      .cwd(directory)
      .env({ ...process.env, PYTHONPATH: "eval" })
      .nothrow()
      .quiet()
    return {
      code: result.exitCode ?? 0,
      stdout: result.stdout.toString(),
      stderr: result.stderr.toString(),
    }
  }

  const parses = (planJson: string) => {
    const line = planJson
      .split("\n")
      .reverse()
      .find((candidate) => candidate.trim().startsWith("{"))
    if (!line) throw new Error("the monitor plan carried no JSON report")
    return JSON.parse(line)
  }

  // Create a child session, prompt it with the role agent, await a bounded
  // terminal, then classify it. Aborts the child on timeout and reaps nothing
  // (the server owns the session), so no process is leaked.
  const dispatchChild = async (
    action: any,
    context: { sessionID: string; directory: string },
    budgetS: number | undefined,
  ) => {
    const role: string = action.role
    const budgetMs = Math.max((budgetS ?? 3600) * 1000, 1000)
    const key = String(action.trial_record)
    let childID: string | undefined

    // Kill a prior dispatch for this trial before starting a new one.
    const prior = activeChildren.get(key)
    if (prior) {
      const stop = client.session.abort({ path: { id: prior }, query: { directory: context.directory } })
      await Promise.resolve(stop).catch(() => {})
      activeChildren.delete(key)
    }

    try {
      const created: any = await client.session.create({
        query: { directory: context.directory },
        body: { title: `eval ${role} ${action.target_id ?? ""}` },
      })
      if (created.error || !created.data) {
        return {
          outcome: RESULT_FAILURE,
          detail: serializeError(created.error) || "session create failed",
        }
      }
      childID = created.data.id as string
      activeChildren.set(key, childID)

      let timer: ReturnType<typeof setTimeout> | undefined
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error("__child_timeout__")), budgetMs)
      })
      let response: any
      try {
        response = await Promise.race([
          client.session.prompt({
            path: { id: childID as string },
            query: { directory: context.directory },
            body: { agent: role, parts: [{ type: "text", text: String(action.message ?? "") }] },
          }),
          timeout,
        ])
      } finally {
        if (timer) clearTimeout(timer)
      }

      if (response.error) {
        return { outcome: RESULT_FAILURE, detail: serializeError(response.error) }
      }
      const info = response.data?.info
      if (info?.error) {
        return { outcome: RESULT_FAILURE, detail: serializeError(info.error) }
      }
      if (action.destination && existsSync(action.destination)) {
        return { outcome: RESULT_SUCCESS, detail: "" }
      }
      return { outcome: RESULT_NO_OUTPUT, detail: `no output at ${action.destination}` }
    } catch (error: any) {
      if (childID) {
        const abort = client.session.abort({ path: { id: childID }, query: { directory: context.directory } })
        await Promise.resolve(abort).catch(() => {})
      }
      if (String(error?.message) === "__child_timeout__") {
        return { outcome: RESULT_TIMEOUT, detail: `child exceeded ${budgetS ?? 3600}s` }
      }
      return { outcome: RESULT_FAILURE, detail: serializeError(error) }
    } finally {
      activeChildren.delete(key)
    }
  }

  const writeResults = (results: unknown[]) => {
    const path = join(tmpdir(), `eval-monitor-results-${process.pid}-${Date.now()}.json`)
    writeFileSync(path, JSON.stringify(results), "utf-8")
    return path
  }

  return {
    tool: {
      eval_monitor: tool({
        description:
          "One tick of the eval harness post-execution workflow control plane. " +
          "The symbolic Python plan engine sweeps every trial record, verifies " +
          "each trial's execution state, and reports the next workflow action; " +
          "this tool performs each assessment/diagnosis dispatch as an awaited " +
          "native opencode child session (bounded, aborted on timeout), applies " +
          "the terminal, and re-plans, so the assessor and the diagnoser run " +
          "synchronously. A failed, blocked, or timed-out execution is deferred " +
          "(the surfer owns recovery). Returns the per-trial state report; exit " +
          "1 means at least one node escalated.",
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
            .describe("seconds a native child dispatch may run before it is aborted"),
          dry_run: tool.schema
            .boolean()
            .optional()
            .describe("report each trial's tick state without dispatching anything"),
        },
        async execute(args, context) {
          const control: string[] = [
            "python3",
            "-m",
            "orchestrator",
            "monitor",
            args.setup,
          ]
          const flag = (name: string, value?: string) => {
            if (value !== undefined && value !== "") control.push(name, value)
          }
          flag("--repo", args.repo)
          flag("--instances-root", args.instances_root)
          flag("--branch", args.branch)
          flag("--state", args.state)
          flag("--runs-root", args.runs_root)
          flag("--data-root", args.data_root)
          flag("--ground-truth", args.ground_truth)
          if (args.budget_s !== undefined) control.push("--budget-s", String(args.budget_s))

          // Dry-run: read the plan only, dispatch nothing.
          if (args.dry_run) {
            const plan = await runCli([...control, "--plan"])
            return {
              title: `eval_monitor ${args.setup}`,
              output: plan.stderr + plan.stdout,
              metadata: { exitCode: plan.code, argv: control },
            }
          }

          let resultsPath: string | undefined
          let lastPlan: any = { actions: [], tally: {}, escalated: 0 }
          const budgetS = args.budget_s === undefined ? 3600 : args.budget_s

          for (let round = 0; round < MAX_APPLY_ROUNDS; round++) {
            const argv = [...control, "--plan"]
            if (resultsPath) argv.push("--results", resultsPath)
            const planRun = await runCli(argv)
            let plan: any
            try {
              plan = parses(planRun.stdout)
            } catch (error: any) {
              return {
                title: `eval_monitor ${args.setup}`,
                output: `monitor plan failed: ${error?.message}\n${planRun.stderr}${planRun.stdout}`,
                metadata: { exitCode: planRun.code || 1, argv },
              }
            }
            lastPlan = plan

            const actions = (plan.actions ?? []).filter(
              (action: any) => action.action === ACTION_DISPATCH,
            )
            const escalations = (plan.actions ?? []).filter(
              (action: any) => action.action === "escalate",
            )
            if (actions.length === 0 && escalations.length === 0) {
              break
            }

            const results: any[] = []
            for (const action of escalations) {
              results.push({
                trial_record: action.trial_record,
                node: action.node,
                escalate: true,
                cause: action.cause,
              })
            }
            for (const action of actions) {
              const terminal = await dispatchChild(action, context, budgetS)
              results.push({
                trial_record: action.trial_record,
                node: action.node,
                outcome: terminal.outcome,
                detail: terminal.detail,
              })
            }
            resultsPath = writeResults(results)
          }

          const tally = Object.entries(lastPlan.tally ?? {})
            .map(([state, count]) => `${state}=${count}`)
            .join(", ")
          const output =
            (lastPlan.actions ?? [])
              .map(
                (action: any) =>
                  `${action.target_id}: ${action.state} (${action.node})` +
                  (action.detail ? `: ${action.detail}` : ""),
              )
              .join("\n") + `\nmonitor tick: ${tally || "no trials"}`
          return {
            title: `eval_monitor ${args.setup}`,
            output,
            metadata: { exitCode: lastPlan.escalated ? 1 : 0, argv: control },
          }
        },
      }),
      next_target: tool({
        description:
          "Advance the multi-target chain by one target on one instance: reclaim " +
          "the previous target's image, pull the next target's image (verified " +
          "present), bring it up, and check its health. On success returns the " +
          "target's image identifiers, the reclaimed/pulled references, and the up " +
          "result; on failure returns the full inspectable trace (step log, command " +
          "error, and traceback) with exit 1.",
        args: {
          setup: tool.schema.string().describe("path to the EvalSetup YAML"),
          instance: tool.schema.string().describe("the instance id"),
          target: tool.schema
            .string()
            .describe("the target_id to advance the chain to"),
          repo: tool.schema
            .string()
            .optional()
            .describe("the canonical eval checkout"),
          instances_root: tool.schema
            .string()
            .optional()
            .describe("where per-instance worktrees live"),
          branch: tool.schema
            .string()
            .optional()
            .describe("the read-only eval branch"),
          chain_state: tool.schema
            .string()
            .optional()
            .describe("the chain position file"),
        },
        async execute(args) {
          const argv: string[] = [
            "python3",
            "-m",
            "orchestrator",
            "next-target",
            args.setup,
            "--instance",
            args.instance,
            "--target",
            args.target,
          ]
          const flag = (name: string, value?: string) => {
            if (value !== undefined && value !== "") argv.push(name, value)
          }
          flag("--repo", args.repo)
          flag("--instances-root", args.instances_root)
          flag("--branch", args.branch)
          flag("--chain-state", args.chain_state)

          const result = await $`${argv}`
            .cwd(directory)
            .env({ ...process.env, PYTHONPATH: "eval" })
            .nothrow()
            .quiet()
          return {
            title: `next_target ${args.instance} -> ${args.target}`,
            output: result.stdout.toString() + result.stderr.toString(),
            metadata: { exitCode: result.exitCode, argv },
          }
        },
      }),
    },
  }
}
