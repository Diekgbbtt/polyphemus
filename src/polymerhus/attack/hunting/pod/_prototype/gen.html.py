"""PROTOTYPE - test-executor pod workflow state machine (throwaway, not production).

Settles the design question: does the pod's re-spec'd workflow (per-stretch ReAct
runner + triager + note-store + tool surface) feel right as a state machine, and
does it yield new/updated phases vs the pre-regrounding scaffold.

The pure module below (the `PodMachine` reducer) is the liftable part: a pure
(state, action) -> state reducer modelling the HIGH-LEVEL workflow map from
docs/design/hunting-67-test-executor-pod-spec.md section 1.3 (D84-16/17). It is
DOM-free and could be lifted into the real graph. The HTML shell after it renders
state and buttons.

Run:  python src/polymerhus/attack/hunting/pod/_prototype/gen.html.py > /tmp/pod-prototype.html
Then open /tmp/pod-prototype.html in a browser and press the walkthrough buttons.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# The pure module (liftable).                                                 #
# --------------------------------------------------------------------------- #

PHASES = ("init", "runner_stretch", "p3_note", "triager", "decide", "terminal")

INITIAL = {
    "phase": "init",
    "iteration": 1,
    "tool_calls": 0,
    "variant_ref": "v0",
    "executed": [],
    "log": {"variants": [], "observations": [], "interpretations": []},
    "memory": {"notes": {}},
    "decision": None,
    "verdict": None,
    "terminal_reason": None,
    "clean": None,
    "tool_surface": ["exec", "kb_retrieve", "note_tool"],
    "kb_primitive_set": None,
    "note_written": False,
}


def reduce(state, action) -> dict:
    """(state, action) -> state. Only legal transitions mutate; illegal actions
    return the state unchanged (disabling the button is the page's job, this
    reducer is the source of legality)."""
    s = {**state, "log": {k: list(v) for k, v in state["log"].items()}}
    a = action

    if s["phase"] == "init" and a == "init_validates":
        return {**s, "phase": "runner_stretch", "iteration": 1, "tool_calls": 0}

    if s["phase"] == "runner_stretch" and a == "runner_tool_call":
        if s["tool_calls"] >= 200:
            return s
        return {**s, "tool_calls": s["tool_calls"] + 1,
                "executed": list(s["executed"]) + [f"sig-{len(s['executed']) + 1}"]}

    if s["phase"] == "runner_stretch" and a == "runner_kb_spaces":
        # P1 concretization: the KB query returns a primitive set; the pool.
        return {**s, "kb_primitive_set": ["GET no-auth", "POST Origin", "token replay"]}

    if s["phase"] == "runner_stretch" and a == "runner_concludes_exhausted":
        # P3: space exhausted - route to the note final step.
        return {**s, "phase": "p3_note"}

    if s["phase"] == "p3_note" and a == "write_consolidated_note":
        # The one consolidated experiment summary, per-variant, in the pod
        # experiment-memory store (spec-keyed with variant children).
        spec_key = "spec:" + (s.get("spec_id") or "root")
        notes = {**s["memory"]["notes"]}
        entries = notes.get(spec_key) or []
        summary = (
            f"[experiment-summary] variant={s['variant_ref']} "
            f"probes={s['executed'].count} kb_pool={s.get('kb_primitive_set')}"
        )
        entries = entries + [summary]
        notes[spec_key] = entries
        return {**s, "phase": "triager", "note_written": True,
                "memory": {**s["memory"], "notes": notes}}

    if s["phase"] == "triager" and a == "triager_reads_note":
        # The triager reads the note (it is in memory[notes]) - no state change
        # beyond the phase; surfacing that the note is its input.
        return {**s, "phase": "decide"}

    if s["phase"] == "decide" and a in (
            "verdict_symptom_confirmed", "verdict_technical_infeasible",
            "verdict_budget_timeout"):
        return {**s, "phase": "terminal",
                "verdict": ("successful" if a == "verdict_symptom_confirmed"
                            else "unsuccessful"),
                "terminal_reason": {
                    "verdict_symptom_confirmed": "symptom-confirmed",
                    "verdict_technical_infeasible": "technical-infeasibility",
                    "verdict_budget_timeout": "budget-timeout",
                }[a],
                "clean": a == "verdict_symptom_confirmed"}

    if s["phase"] == "decide" and a == "verdict_space_exhausted":
        # The KB re-query returns the SAME primitive set -> genuinely exhausted.
        return {**s, "phase": "terminal", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    if s["phase"] == "decide" and a == "mine_variant":
        if s["iteration"] >= 8:
            return {**s, "phase": "terminal", "verdict": "unsuccessful",
                    "terminal_reason": "budget-timeout", "clean": False}
        ref = f"v{len(s['log']['variants']) + 1}"
        return {**s, "phase": "runner_stretch",
                "iteration": s["iteration"] + 1, "variant_ref": ref,
                "tool_calls": 0,
                "log": {**s["log"],
                        "variants": s["log"]["variants"]
                        + [{"ref": ref, "parent": s["variant_ref"]}]}}

    return s


def emit() -> str:
    import json

    return PAGE


# --------------------------------------------------------------------------- #
# The HTML shell (throwaway).                                                 #
# --------------------------------------------------------------------------- #

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Test-executor pod workflow - prototype</title>
<style>
  :root { --accent:#2563eb; --bg:#f8fafc; --card:#fff; --line:#e2e8f0; }
  * { box-sizing:border-box; }
  body { font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:#0f172a; margin:0; padding:2rem 1rem; }
  .wrap { max-width:880px; margin:0 auto; }
  h1 { font-size:1.3rem; margin:0 0 0.25rem; }
  .intro { color:#475569; font-size:0.9rem; line-height:1.5; margin-bottom:1.25rem; }
  h2 { font-size:1rem; margin:1.5rem 0 0.5rem; }
  .state { background:var(--card); border:1px solid var(--line); border-radius:8px;
           padding:1rem 1.25rem; font-size:0.85rem; }
  .state .row { margin-bottom:0.3rem; }
  .state .lbl { color:#64748b; font-weight:600; }
  .pill { display:inline-block; padding:0.1rem 0.6rem; border-radius:999px;
          font-size:0.75rem; font-weight:600; }
  .pill.init{background:#e0e7ff;color:#3730a3;} .pill.runner_stretch{background:#dcfce7;color:#166534;}
  .pill.p3_note{background:#e0f2fe;color:#075985;} .pill.triager{background:#fef9c3;color:#854d0e;}
  .pill.decide{background:#fee2e2;color:#991b1b;} .pill.terminal{background:#ddd6fe;color:#4c1d95;}
  .btns { display:flex; flex-wrap:wrap; gap:0.5rem; margin:0.75rem 0; }
  button { border:1px solid var(--line); background:var(--card); color:#0f172a;
           padding:0.45rem 0.9rem; border-radius:6px; cursor:pointer; font-size:0.85rem; }
  button:hover { border-color:var(--accent); color:var(--accent); }
  button:disabled { opacity:0.35; cursor:not-allowed; }
  .tabs { display:flex; gap:0.25rem; border-bottom:1px solid var(--line); margin-bottom:1rem; }
  .tabs button { border:1px solid var(--line); border-bottom:none; border-radius:6px 6px 0 0; }
  .tabs button.active { background:var(--accent); color:#fff; }
  .scen { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:1rem 1.25rem; }
  .scen p { font-size:0.85rem; color:#475569; margin:0 0 0.6rem; }
  .cmt { font-size:0.8rem; color:#16a34a; margin-top:0.5rem; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Test-executor pod workflow - prototype</h1>
  <div class="intro">
    Model: the pod's HIGH-LEVEL workflow map (spec 1.3, D84-16/17). One probe
    stretch = a single ReAct <code>stateful_turn</code>; on space exhaustion a
    consolidated experiment note is written to the pod memory store; the triager
    reads the note and either terminates (six-way vocabulary) or mines a
    variant. The KB query surfaces the payload-pool; the tool surface is
    <code>[exec, kb_retrieve, note_tool]</code>.
    <strong>Question:</strong> does this state machine and its phases feel
    right, and do the phases it yields (P3-note, triager-reads-note) change the
    pre-regrounding PROBE/EXECUTE/OBSERVE/INTERPRET split?
  </div>

  <h2>Current state</h2>
  <div class="state" id="state"></div>

  <h2>Free-play</h2>
  <div class="btns" id="buttons"></div>

  <h2>Guided walkthroughs</h2>
  <div class="tabs" id="tabs"></div>
  <div class="scen">
    <p id="scenText"></p>
    <div class="btns" id="scenBtns"></div>
    <div class="cmt" id="cmt"></div>
  </div>
</div>

<script>
"use strict";

// ---- the pure reducer (liftable) ------------------------------------------
var PHASES = ["init","runner_stretch","p3_note","triager","decide","terminal"];
var INITIAL = {phase:"init", iteration:1, tool_calls:0, variant_ref:"v0",
  executed:[], log:{variants:[],observations:[],interpretations:[]},
  memory:{notes:{}}, decision:null, verdict:null, terminal_reason:null,
  clean:null, tool_surface:["exec","kb_retrieve","note_tool"],
  kb_primitive_set:null, note_written:false};
function reduce(state, action) {
  var s = JSON.parse(JSON.stringify(state));
  if (s.phase === "init" && action === "init_validates") {
    return Object.assign(s, {phase:"runner_stretch", iteration:1, tool_calls:0});
  }
  if (s.phase === "runner_stretch" && action === "runner_tool_call") {
    if (s.tool_calls >= 200) return s;
    return Object.assign(s, {tool_calls: s.tool_calls + 1,
      executed: s.executed.concat("sig-"+(s.executed.length+1))});
  }
  if (s.phase === "runner_stretch" && action === "runner_kb_spaces") {
    return Object.assign(s, {kb_primitive_set:["GET no-auth","POST Origin","token replay"]});
  }
  if (s.phase === "runner_stretch" && action === "runner_concludes_exhausted") {
    return Object.assign(s, {phase:"p3_note"});
  }
  if (s.phase === "p3_note" && action === "write_consolidated_note") {
    var specKey = "spec:root";
    var entries = (s.memory.notes[specKey] || []).concat(
      "[experiment-summary] variant="+s.variant_ref+" probes="+s.executed.length+
      " kb_pool="+JSON.stringify(s.kb_primitive_set));
    s.memory.notes[specKey] = entries;
    return Object.assign(s, {phase:"triager", note_written:true});
  }
  if (s.phase === "triager" && action === "triager_reads_note") {
    return Object.assign(s, {phase:"decide"});
  }
  if (s.phase === "decide" &&
      ["verdict_symptom_confirmed","verdict_technical_infeasible",
       "verdict_budget_timeout"].indexOf(action) >= 0) {
    var reason = {verdict_symptom_confirmed:"symptom-confirmed",
      verdict_technical_infeasible:"technical-infeasibility",
      verdict_budget_timeout:"budget-timeout"}[action];
    return Object.assign(s, {phase:"terminal",
      verdict: action === "verdict_symptom_confirmed" ? "successful" : "unsuccessful",
      terminal_reason: reason,
      clean: action === "verdict_symptom_confirmed"});
  }
  if (s.phase === "decide" && action === "verdict_space_exhausted") {
    return Object.assign(s, {phase:"terminal", verdict:"unsuccessful",
      terminal_reason:"space-exhausted", clean:true});
  }
  if (s.phase === "decide" && action === "mine_variant") {
    if (s.iteration >= 8) {
      return Object.assign(s, {phase:"terminal", verdict:"unsuccessful",
        terminal_reason:"budget-timeout", clean:false});
    }
    var ref = "v" + (s.log.variants.length + 1);
    s.log.variants.push({ref:ref, parent:s.variant_ref});
    return Object.assign(s, {phase:"runner_stretch", iteration:s.iteration+1,
      variant_ref:ref, tool_calls:0});
  }
  return s;
}

// ---- the page shell (throwaway) -------------------------------------------
var ACTIONS = {"init_validates":"INIT validates spec",
  "runner_tool_call":"Runner issues one tool call (ReAct)",
  "runner_kb_spaces":"Runner queries KB -> payload pool (P1)",
  "runner_concludes_exhausted":"Runner: space exhausted (P3)",
  "write_consolidated_note":"Write consolidated experiment note",
  "triager_reads_note":"Triager reads the note",
  "verdict_symptom_confirmed":"Terminate: symptom-confirmed",
  "verdict_space_exhausted":"Terminate: space-exhausted",
  "verdict_technical_infeasible":"Terminate: technical-infeasibility",
  "verdict_budget_timeout":"Terminate: budget-timeout",
  "mine_variant":"Mine a new variant"};

function legal(s, a) {
  return JSON.stringify(reduce(s, a)) !== JSON.stringify(JSON.parse(JSON.stringify(s)));
}

var state = JSON.parse(JSON.stringify(INITIAL));

function render() {
  var el = document.getElementById("state");
  var rows = [];
  rows.push('<div class="row"><span class="lbl">phase:</span> ' +
    '<span class="pill ' + state.phase + '">' + state.phase + '</span></div>');
  rows.push('<div class="row"><span class="lbl">iteration:</span> ' + state.iteration +
    ' &nbsp; <span class="lbl">variant:</span> ' + state.variant_ref +
    ' &nbsp; <span class="lbl">tool_calls:</span> ' + state.tool_calls + '</div>');
  rows.push('<div class="row"><span class="lbl">tool surface:</span> ' +
    state.tool_surface.join(", ") + '</div>');
  rows.push('<div class="row"><span class="lbl">kb payload pool:</span> ' +
    JSON.stringify(state.kb_primitive_set) + '</div>');
  rows.push('<div class="row"><span class="lbl">executed probes:</span> ' +
    state.executed.length + ' &nbsp; <span class="lbl">variants:</span> ' +
    JSON.stringify(state.log.variants) + '</div>');
  rows.push('<div class="row"><span class="lbl">note written:</span> ' +
    state.note_written + ' &nbsp; <span class="lbl">note store:</span> ' +
    JSON.stringify(state.memory.notes) + '</div>');
  rows.push('<div class="row"><span class="lbl">verdict:</span> ' + state.verdict +
    ' &nbsp; <span class="lbl">terminal_reason:</span> ' + state.terminal_reason +
    ' &nbsp; <span class="lbl">clean:</span> ' + state.clean + '</div>');
  el.innerHTML = rows.join("");

  var btns = document.getElementById("buttons");
  btns.innerHTML = "";
  Object.keys(ACTIONS).forEach(function(a) {
    var b = document.createElement("button");
    b.textContent = ACTIONS[a];
    b.disabled = !legal(state, a);
    b.onclick = function() { state = reduce(state, a); render(); };
    btns.appendChild(b);
  });
}
render();

// ---- walkthroughs ---------------------------------------------------------
var SCENARIOS = {
  "Happy: confirmed": {
    desc: "Valid spec, INIT accepts, the runner probes, the KB pools the payload " +
      "space, the symptom is observed and the pod terminates successful.",
    steps: ["init_validates","runner_tool_call","runner_kb_spaces",
      "verdict_symptom_confirmed"]},
  "Exhausted + note": {
    desc: "The probe space exhausts; the runner writes ONE consolidated note " +
      "(P3), the triager reads it and the KB re-query confirms the same pool -> " +
      "space-exhausted.",
    steps: ["init_validates","runner_tool_call","runner_kb_spaces",
      "runner_concludes_exhausted","write_consolidated_note",
      "triager_reads_note","verdict_space_exhausted"]},
  "Variant loop then budget": {
    desc: "The triager mines variants up to HUNT_POD_MAX_ITERS (8); past the cap " +
      "budget-timeout terminates. Watch iteration climb and tool_calls reset.",
    steps: ["init_validates","mine_variant","mine_variant","mine_variant",
      "mine_variant","mine_variant","mine_variant","mine_variant","mine_variant"]},
  "Infeasible": {
    desc: "Unreachable target or a blocked tool -> technical-infeasibility, " +
      "clean=false.",
    steps: ["init_validates","verdict_technical_infeasible"]},
  "Legality (shift-click no-op)": {
    desc: "Try a terminal verdict while the runner is mid-stretch - the reducer " +
      "rejects it (state unchanged). The buttons disable on illegal actions.",
    steps: ["init_validates","verdict_budget_timeout","runner_tool_call"]}
};

var tabs = document.getElementById("tabs");
var active = "Happy: confirmed";
Object.keys(SCENARIOS).forEach(function(name) {
  var t = document.createElement("button");
  t.textContent = name;
  if (name === active) t.className = "active";
  t.onclick = function() {
    active = name;
    state = JSON.parse(JSON.stringify(INITIAL));
    render();
    var btns = document.querySelectorAll("#tabs button");
    btns.forEach(function(b){ b.classList.remove("active"); });
    t.classList.add("active");
    document.getElementById("cmt").textContent = "";
    renderScenario();
  };
  tabs.appendChild(t);
});

function renderScenario() {
  var sc = SCENARIOS[active];
  document.getElementById("scenText").textContent = sc.desc;
  var box = document.getElementById("scenBtns");
  box.innerHTML = "";
  var i = 0;
  function addNext() {
    if (i >= sc.steps.length) return;
    var b = document.createElement("button");
    b.textContent = "Step " + (i+1) + ": " + ACTIONS[sc.steps[i]];
    b.onclick = function() {
      var a = sc.steps[i];
      if (!legal(state, a)) {
        document.getElementById("cmt").textContent =
          "Step " + (i+1) + " (" + a + ") is ILLEGAL from this state - reducer returned state unchanged.";
        return;
      }
      state = reduce(state, a);
      render();
      document.getElementById("cmt").textContent = "Step " + (i+1) + " done: " + ACTIONS[a];
      i += 1;
      box.innerHTML = "";
      addNext();
      if (i >= sc.steps.length) {
        document.getElementById("cmt").textContent += " - walkthrough complete";
      }
    };
    box.appendChild(b);
    addNext();
  }
  addNext();
}
renderScenario();
</script>
</body>
</html>"""

if __name__ == "__main__":
    print(PAGE)