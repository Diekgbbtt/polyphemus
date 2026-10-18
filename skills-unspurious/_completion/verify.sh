#!/usr/bin/env bash
# W0+W1 completion machine checks.
# Run from the worktree root after every phase; paste the result into
# docs/design/w0-w1-completion-ledger.md.
# Later-phase checks report PENDING until their artefact exists, so the same
# script is valid after every phase. Exit code is non-zero on any FAIL.

set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 2

fail=0
pending_count=0
pass() { printf 'PASS  %s\n' "$1"; }
failed() { printf 'FAIL  %s\n' "$1"; fail=1; }
pending() { printf 'PENDING  %s\n' "$1"; pending_count=$((pending_count + 1)); }

echo "== W0+W1 completion checks ($(date -u +%Y-%m-%dT%H:%MZ)) =="

# 1. No stale validation status in the two validated docs.
if grep -rq 'awaiting operator review' docs/design/skills-variant-boundary.md docs/design/skills-ontology.md; then
  failed "no stale 'awaiting operator review' in boundary/ontology"
else
  pass "no stale 'awaiting operator review' in boundary/ontology"
fi

# 2. Stale agnosticism lines gone and the skill section absent.
if grep -rq 'block stays\|left in place and flagged' skills-unspurious/llm-prompt-injection/; then
  failed "no stale Framework-Specific claim in llm-prompt-injection"
elif grep -rq '^## Framework-Specific' skills-unspurious/llm-prompt-injection/; then
  failed "llm-prompt-injection carries no Framework-Specific section"
else
  pass "stale agnosticism lines gone; llm-prompt-injection carries no Framework-Specific"
fi

# 3. The ontology references the boundary.
if grep -q 'skills-variant-boundary.md' docs/design/skills-ontology.md; then
  pass "skills-ontology.md references the boundary"
else
  failed "skills-ontology.md references the boundary"
fi

# 4. The cross-stream doc is tracked and its citations resolve.
if git ls-files --error-unmatch docs/design/skills-system-decomposition.md >/dev/null 2>&1; then
  if grep -rq 'skills-system-decomposition.md' docs/design/skills-variant-boundary.md docs/design/skills-ontology.md skills-unspurious/_analysis/SPEC.md; then
    pass "cross-stream doc tracked; citations present"
  else
    failed "cross-stream doc citations present"
  fi
else
  failed "cross-stream doc tracked"
fi

# 5. The arsenal-gaps ticket exists and is linked.
if command -v gh >/dev/null 2>&1; then
  if gh issue view 303 --json number >/dev/null 2>&1; then
    if grep -q '#303' skills-unspurious/SCREAMING-REPORT.md; then
      pass "arsenal ticket #303 exists and is linked from SCREAMING-REPORT"
    else
      failed "SCREAMING-REPORT links arsenal ticket #303"
    fi
  else
    failed "arsenal ticket #303 exists"
  fi
else
  pending "arsenal ticket #303 (gh not available)"
fi

# 6. The taxonomy document exists (B1).
if [ -f docs/design/skills-taxonomy.md ]; then
  pass "taxonomy document exists"
else
  pending "taxonomy document (B1)"
fi

# 7. The two families exist and no dangling family reference remains (C1/C2).
fam_ok=1
for fam in defence-bypass proxy-techniques; do
  if [ ! -f "skills-unspurious/$fam/SKILL.md" ]; then fam_ok=0; fi
done
if [ "$fam_ok" = "1" ]; then
  pass "defence-bypass and proxy-techniques families exist"
else
  pending "defence-bypass / proxy-techniques families (C1)"
fi

# 8. The 101 CLASS children exist (the two family groups are excluded from the
# class count), each family parent's `## Variants` line set equals its child
# leaf set (R9), and name == directory for every level-2 skill (family leaves
# included).
class_children=$(find skills-unspurious -mindepth 3 -maxdepth 3 -name SKILL.md \
  -not -path 'skills-unspurious/defence-bypass/*' \
  -not -path 'skills-unspurious/proxy-techniques/*' | wc -l | tr -d ' ')
if [ "$class_children" = "101" ]; then
  pass "101 class child SKILL.md present (found $class_children)"
else
  failed "101 class child SKILL.md present (found $class_children)"
fi

fam_ok=1
for fam in defence-bypass proxy-techniques; do
  parent="skills-unspurious/$fam/SKILL.md"
  if [ ! -f "$parent" ]; then
    printf '      family parent missing: %s\n' "$parent"
    fam_ok=0
    continue
  fi
  listed=$(awk '/^## Variants$/{f=1;next} f && /^## /{exit} f && /^- /{sub(/^- /,""); sub(/ - .*/,""); print}' "$parent" | sort)
  leaves=$(find "skills-unspurious/$fam" -mindepth 2 -maxdepth 2 -name SKILL.md | sed 's|/SKILL.md$||; s|.*/||' | sort)
  if [ "$listed" != "$leaves" ]; then
    printf '      %s: ## Variants lines != child leaves\n' "$fam"
    printf '        listed: %s\n' "$(printf '%s' "$listed" | tr '\n' ' ')"
    printf '        leaves: %s\n' "$(printf '%s' "$leaves" | tr '\n' ' ')"
    fam_ok=0
  fi
done
if [ "$fam_ok" = "1" ]; then
  pass "each family parent's ## Variants lines equal its child leaves (R9)"
else
  failed "each family parent's ## Variants lines equal its child leaves (R9)"
fi

mismatch=0
while IFS= read -r f; do
  dir=$(basename "$(dirname "$f")")
  name=$(grep -m1 '^name:' "$f" | sed 's/^name:[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//')
  if [ "$dir" != "$name" ]; then
    printf '      name mismatch: %s (name=%s)\n' "$f" "$name"
    mismatch=1
  fi
done < <(find skills-unspurious -mindepth 3 -maxdepth 3 -name SKILL.md)
if [ "$mismatch" = "0" ]; then
  pass "every child frontmatter name equals its directory"
else
  failed "every child frontmatter name equals its directory"
fi

# 9. No em dashes in authored Markdown (U+2014, built from bytes to avoid a literal).
emdash=$(printf '\342\200\224')
targets="skills-unspurious docs/design/skills-variant-boundary.md docs/design/skills-ontology.md docs/design/skills-system-decomposition.md docs/design/skills-taxonomy.md docs/design/skills-taxonomy-decisions.md docs/design/skill-evolution-w3-decisions.md docs/design/skills-system-fsm.md docs/design/w0-w1-completion-ledger.md"
if grep -rl "$emdash" $targets >/dev/null 2>&1; then
  printf 'FAIL  no em dashes in authored Markdown; offenders:\n'
  grep -rln "$emdash" $targets | sed 's/^/      /'
  fail=1
else
  pass "no em dashes in authored Markdown"
fi

if [ "$fail" != 0 ]; then
  summary="FAILURES-PRESENT"
elif [ "$pending_count" != 0 ]; then
  summary="NO-FAILURES ($pending_count pending)"
else
  summary="ALL-CHECKS-PASS"
fi
echo "== $summary =="
exit "$fail"
