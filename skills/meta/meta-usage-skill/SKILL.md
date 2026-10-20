---
name: meta-usage-skill
description: Judge a loaded skill against its stated observables after execution and record reusable lessons through record_skill_lesson.
metadata:
  version: '1.2'
---
# Judging the skill just run

1. After the skill's run, match seen sights against the observable each step states; a step stating none is itself the gap, citing that step.
Observable: each gap cites its step plus seen-versus-stated.
2. Keep only reusable lessons grounded on objective evidence from the run, seen twice in this run or once with its trigger named from the run, defensible from any perspective, unbiased by role and path; leave unrecorded a miss naming the skipped sight the loaded body already stated, and single samples without a trigger.
Observable: each kept lesson names its step plus recurrence or trigger.
3. Scope each kept lesson to the RDF notion it concerns - the skill section its observation belongs to: Attack Surface, Reconnaissance, Detection Channels, Adversarial Capabilities, Trust Assumptions, Key Vulnerabilities, Advanced Techniques, Bypass Techniques, Chaining Attacks, Testing Methodology, False Positives, Pro Tips, Tooling, Summary, or the scripted tests in `references/`; name that notion in the lesson prose and keep the lesson inside it, naming the one notion whose content would change when two are involved.
Observable: each kept lesson names one notion from that list.
4. Record each kept lesson through `record_skill_lesson` with exactly `skill`, `type`, `lesson`, `expected`, `evidence`; `type` is `specification` (knowledge specific to the target, an addition about its attack surface), `extension` (an extension of the procedure: new steps, an optimised grouping, an anti-pattern - steps that must not be done - or an extension of the technique's scope), or `defect` (a genuine error in the illustrated procedure); the store stamps key, base version, writing agent identity, and timestamp, and refuses a skill whose version does not resolve.
Observable: the envelope reports `ok` with the generated key, or `lesson_invalid`/`skill_unknown`/`store_unavailable` naming its correction.
5. Never call `write_skill`: revisions belong to the SkillEvolver; the usage protocol records lessons only.
Observable: no `write_skill` call leaves this run.
6. Judge once per run; a recorded lesson closes the run; a failed envelope means correct the record and retry once, then the run moves on.
Observable: one judgement per run; at most one retry after a failed envelope.
