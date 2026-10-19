#!/usr/bin/env bash
# W0+W1 completion machine checks.
# Run from the worktree root after every phase; paste the result into
# docs/design/w0-w1-completion-ledger.md.
# Later-phase checks report PENDING until their artefact exists, so the same
# script is valid after every phase. Exit code is non-zero on any FAIL.

set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 2

# The suite now lives at the live catalogue root: these are its 39 class and 2
# family group directories. The other live-root skills (the flat corpus, the
# anatomy skills, the meta family) keep their old layouts and are NOT scanned
# by the suite-scoped checks below; the stream records stay in
# `skills-unspurious/`.
SUITE_ROOT="skills"
SUITE_GROUPS=(
  account-recovery
  authentication-jwt
  broken-function-level-authorization
  business-logic
  cache-poisoning
  crypto-weakness
  csrf
  defence-bypass
  email-header-injection
  graphql
  header-injection
  http-method-tampering
  http-parameter-pollution
  http-request-smuggling
  idor
  information-disclosure
  insecure-deserialization
  insecure-file-uploads
  ldap-injection
  llm-prompt-injection
  mass-assignment
  mfa-bypass
  nosql-injection
  oauth
  open-redirect
  path-traversal-lfi-rfi
  prototype-pollution
  proxy-techniques
  race-conditions
  rate-limit-bypass
  rce
  session-management
  sql-injection
  ssrf
  ssti
  subdomain-takeover
  two-principal-authz
  weak-credential-discovery
  xpath-injection
  xss
  xxe
)

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
if grep -rq 'block stays\|left in place and flagged' "$SUITE_ROOT/llm-prompt-injection/"; then
  failed "no stale Framework-Specific claim in llm-prompt-injection"
elif grep -rq '^## Framework-Specific' "$SUITE_ROOT/llm-prompt-injection/"; then
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

# 7. The two families exist and no dangling family reference remains (C1/C2):
# a family mention must use the family name, because only the name resolves.
# The implicit forms ("the bypass family", "the proxy family") and the stale
# pre-C1 phrasing ("the future ... family") are the dangling forms. The scan is
# suite-scoped: the non-suite live-root skills are not part of the suite.
missing_groups=()
leftover_groups=()
for group in "${SUITE_GROUPS[@]}"; do
  [ -f "$SUITE_ROOT/$group/SKILL.md" ] || missing_groups+=("$group")
  [ -e "skills-unspurious/$group" ] && leftover_groups+=("$group")
done
if [ "${#missing_groups[@]}" = "0" ]; then
  pass "all ${#SUITE_GROUPS[@]} suite group directories are at the live root"
else
  printf 'FAIL  suite group directories missing at the live root:%s\n' " ${missing_groups[*]}"
  fail=1
fi
if [ "${#leftover_groups[@]}" = "0" ]; then
  pass "no suite group directory remains under skills-unspurious"
else
  printf 'FAIL  suite group directories still under skills-unspurious:%s\n' " ${leftover_groups[*]}"
  fail=1
fi

# The replacement boundary: the non-suite live-root skills stay untouched (the
# anatomy skills, the meta family, and a sample of the corpus's tool and
# technology skills).
keep_ok=1
for keep in \
  webpage-analysis webpage-profile lightrag-query steel-browser \
  webapp-clientside-semantic-model authorization-pyramid \
  meta/meta-usage-skill meta/meta-write-skill meta/authn-skill-writing \
  ffuf nmap semgrep windows-ad; do
  [ -f "$SUITE_ROOT/$keep/SKILL.md" ] || { printf '      missing non-suite skill: %s\n' "$keep"; keep_ok=0; }
done
if [ "$keep_ok" = "1" ]; then
  pass "the non-suite live-root skills stay in place"
else
  failed "the non-suite live-root skills stay in place"
fi

fam_ok=1
for fam in defence-bypass proxy-techniques; do
  if [ ! -f "$SUITE_ROOT/$fam/SKILL.md" ]; then fam_ok=0; fi
done
if [ "$fam_ok" = "1" ]; then
  pass "defence-bypass and proxy-techniques families exist"
else
  pending "defence-bypass / proxy-techniques families (C1)"
fi

dangling=()
for group in "${SUITE_GROUPS[@]}"; do
  while IFS= read -r f; do
    [ -n "$f" ] && dangling+=("$f")
  done < <(grep -rlE 'the bypass family|the proxy family|future (defence-bypass|proxy-techniques|bypass|proxy)' "$SUITE_ROOT/$group" --include=SKILL.md || true)
done
if [ "${#dangling[@]}" = "0" ]; then
  pass "every family reference in a SKILL.md uses the family name"
else
  printf 'FAIL  every family reference in a SKILL.md uses the family name; offenders:\n'
  printf '%s\n' "${dangling[@]}" | sed 's/^/      /'
  fail=1
fi

# 8. The CLASS children exist, and every decomposing group parent's `## Variants`
# line set equals its own child leaf set (R9), with no `## Variants` on a group
# that has no children (R10). The class-children count is a floor: the ratified
# floor is 101 (B1) and later authoring grows it, so the check pairs the floor
# with the per-parent sweep instead of freezing the number. Name == directory is
# swept for every suite SKILL.md, the level-1 parents included (R3). The sweep
# is suite-scoped: the non-suite live-root skills keep their old layouts.
class_children=$(for group in "${SUITE_GROUPS[@]}"; do
  case "$group" in defence-bypass|proxy-techniques) continue ;; esac
  find "$SUITE_ROOT/$group" -mindepth 2 -maxdepth 2 -name SKILL.md
done | wc -l | tr -d ' ')
if [ "$class_children" -ge 101 ]; then
  pass "class child SKILL.md count is at or above the ratified floor of 101 (found $class_children)"
else
  failed "class child SKILL.md count is at or above the ratified floor of 101 (found $class_children)"
fi

variant_ok=1
for group_name in "${SUITE_GROUPS[@]}"; do
  group="$SUITE_ROOT/$group_name"
  parent="$group/SKILL.md"
  [ -f "$parent" ] || continue
  leaves=$(find "$group" -mindepth 2 -maxdepth 2 -name SKILL.md | sed 's|/SKILL.md$||; s|.*/||' | sort)
  if [ -z "$leaves" ]; then
    if grep -q '^## Variants$' "$parent"; then
      printf '      %s: ## Variants present with no child leaves\n' "$group"
      variant_ok=0
    fi
    continue
  fi
  listed=$(awk '/^## Variants$/{f=1;next} f && /^## /{exit} f && /^- /{sub(/^- /,""); sub(/ - .*/,""); print}' "$parent" | sort)
  if [ "$listed" != "$leaves" ]; then
    printf '      %s: ## Variants lines != child leaves\n' "$group"
    printf '        listed: %s\n' "$(printf '%s' "$listed" | tr '\n' ' ')"
    printf '        leaves: %s\n' "$(printf '%s' "$leaves" | tr '\n' ' ')"
    variant_ok=0
  fi
done
if [ "$variant_ok" = "1" ]; then
  pass "every decomposing parent's ## Variants lines equal its child leaves (R9/R10)"
else
  failed "every decomposing parent's ## Variants lines equal its child leaves (R9/R10)"
fi

# The two family leaves follow R5 (`<family>-<discriminator>`), so every leaf
# authored after the C1 pass, the D1b leaves included, is covered by name as
# well as by the parent sweep above.
prefix_bad=""
for fam in defence-bypass proxy-techniques; do
  for leaf in $(find "$SUITE_ROOT/$fam" -mindepth 2 -maxdepth 2 -name SKILL.md | sed 's|/SKILL.md$||; s|.*/||'); do
    case "$leaf" in
      "$fam"-*) ;;
      *) prefix_bad="$prefix_bad $leaf" ;;
    esac
  done
done
if [ -z "$prefix_bad" ]; then
  pass "every family leaf name starts with its family prefix (R5)"
else
  printf 'FAIL  every family leaf name starts with its family prefix (R5); offenders:%s\n' "$prefix_bad"
  fail=1
fi

mismatch=0
while IFS= read -r f; do
  dir=$(basename "$(dirname "$f")")
  name=$(grep -m1 '^name:' "$f" | sed 's/^name:[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//')
  if [ "$dir" != "$name" ]; then
    printf '      name mismatch: %s (name=%s)\n' "$f" "$name"
    mismatch=1
  fi
done < <(for group_name in "${SUITE_GROUPS[@]}"; do find "$SUITE_ROOT/$group_name" -name SKILL.md; done)
if [ "$mismatch" = "0" ]; then
  pass "every SKILL.md frontmatter name equals its directory"
else
  failed "every SKILL.md frontmatter name equals its directory"
fi

# 9. No em dashes in authored Markdown (U+2014, built from bytes to avoid a literal).
# The scan covers the suite groups (not the other live-root skills) plus the
# stream records and the design documents.
emdash=$(printf '\342\200\224')
targets="skills/README.md skills-unspurious docs/design/skills-variant-boundary.md docs/design/skills-ontology.md docs/design/skills-system-decomposition.md docs/design/skills-taxonomy.md docs/design/skills-taxonomy-decisions.md docs/design/skill-evolution-w3-decisions.md docs/design/skills-system-fsm.md docs/design/w0-w1-completion-ledger.md"
for group in "${SUITE_GROUPS[@]}"; do targets="$targets $SUITE_ROOT/$group"; done
if grep -rl "$emdash" $targets >/dev/null 2>&1; then
  printf 'FAIL  no em dashes in authored Markdown; offenders:\n'
  grep -rln "$emdash" $targets | sed 's/^/      /'
  fail=1
else
  pass "no em dashes in authored Markdown"
fi

# 10. Every non-family SKILL.md that carries a `## Bypass Techniques` section
# closes it with the canonical extended-reading pointer to the two families,
# exactly once, as the section's last record. The two family bundles ARE the
# extended reading, so they are exempt. The scan is suite-scoped.
pointer="- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families."
pointer_bad=""
for group_name in "${SUITE_GROUPS[@]}"; do
  case "$group_name" in defence-bypass|proxy-techniques) continue ;; esac
  for f in $(grep -rlE '^## Bypass Techniques' "$SUITE_ROOT/$group_name" --include=SKILL.md || true); do
    if [ "$(grep -cF -e "$pointer" "$f")" != "1" ]; then pointer_bad="$pointer_bad $f"; fi
  done
done
if [ -z "$pointer_bad" ]; then
  pass "every class bypass section carries the extended-reading pointer once"
else
  printf 'FAIL  every class bypass section carries the extended-reading pointer once; offenders:%s\n' "$pointer_bad"
  fail=1
fi

# 11. The reference layout of the twelve enumerable sections. Every non-blank,
# non-heading, non-fence, non-indented line there is one record
# (`- **<identifier>**: <content>.`): no prose paragraph, no numbered item, and
# no bare `**Group**` line in a variant. A level-1 class parent keeps its
# `**Group**` labels above its records, which is the reference-native
# organisation of the parent layer, so the bare-bold line is allowed there and
# only there. `## Variants` is exempt because checks 8's R9/R10 sweep parses its
# line set, and the out-of-scope sections (front matter, title, intro, Testing
# Methodology, Summary) keep their prose by the spec's section 4.
# Two sibling shapes are offenders too: a blank line between two records, while
# a blank line around a heading (the `## ` opener or a `###` group label) stays
# legal; and an indented line outside a code fence, because the only indented
# lines the contract allows are the abstract fences, which carry a two-space
# indent. An indented prose or numbered line is therefore an offender.
# The scan is awk-based on purpose: a `grep -n` prefix defeats an anchored `-v`
# filter, so the line-number form is built only for the offender report.
# The scan runs per suite group, so the live root's other skills (the flat
# corpus, the anatomy skills, the meta family) keep their old layouts untouched.
layout_scan() {
  local root="$1" out="$2"
  find "$root" -name SKILL.md -print | sort | while IFS= read -r f; do
    rel="${f#"$root"/}"
    cp_flag=0
    # Relative to a group root, the group parent is the only file with no
    # sub-directory segment; a leaf sits one level below it.
    case "$rel" in
      */*) ;;
      *) cp_flag=1 ;;
    esac
    awk -v cp="$cp_flag" '
      function inscope_head(h) {
        return h == "## Attack Surface" || h == "## Reconnaissance" || \
               h == "## Detection Channels" || h == "## Adversarial Capabilities" || \
               h == "## Trust Assumptions" || h == "## Key Vulnerabilities" || \
               h == "## Advanced Techniques" || h == "## Bypass Techniques" || \
               h == "## Chaining Attacks" || h == "## False Positives" || \
               h == "## Pro Tips" || h == "## Tooling"
      }
      BEGIN { inscope = 0; fence = 0; prev = ""; blanks = "" }
      /^## / { inscope = inscope_head($0); fence = 0; prev = "heading"; blanks = ""; next }
      {
        if (!inscope) next
        if ($0 ~ /^[[:space:]]*```/) { fence = !fence; prev = "fence"; blanks = ""; next }
        if (fence) next
        if ($0 ~ /^[[:space:]]*$/) { blanks = blanks " " FNR; next }
        if ($0 ~ /^#/) { prev = "heading"; blanks = ""; next }
        if (prev == "record" && $0 ~ /^- \*\*[^*]+\*\*: .+\.$/) {
          n = split(blanks, b, " ")
          for (i = 1; i <= n; i++)
            printf "%s:%s: blank line between records\n", FILENAME, b[i]
        }
        blanks = ""
        if ($0 ~ /^[[:space:]]/) {
          printf "%s:%d: indented line outside a code fence: %s\n", FILENAME, FNR, $0
          prev = "other"; next
        }
        if ($0 ~ /^- \*\*[^*]+\*\*: .+\.$/) { prev = "record"; next }
        if ($0 ~ /^[0-9]+\./) {
          printf "%s:%d: numbered item: %s\n", FILENAME, FNR, $0; prev = "other"; next
        }
        if ($0 ~ /^\*\*[^*]+\*\*$/ && cp == 1) { prev = "group"; next }
        if ($0 ~ /^\*\*[^*]+\*\*$/) {
          printf "%s:%d: bare group header: %s\n", FILENAME, FNR, $0; prev = "other"; next
        }
        printf "%s:%d: not a record: %s\n", FILENAME, FNR, $0
        prev = "other"
      }
    ' "$f" >> "$out"
  done
}
layout_tmp="${TMPDIR:-/tmp}/skills-layout-$$.txt"
: > "$layout_tmp"
for group in "${SUITE_GROUPS[@]}"; do
  layout_scan "$SUITE_ROOT/$group" "$layout_tmp"
done
if [ -s "$layout_tmp" ]; then
  printf 'FAIL  every enumerable-section line is a reference record; offenders:\n'
  sed 's/^/      /' "$layout_tmp"
  fail=1
else
  pass "every enumerable-section line is a reference record"
fi
rm -f "$layout_tmp"

if [ "$fail" != 0 ]; then
  summary="FAILURES-PRESENT"
elif [ "$pending_count" != 0 ]; then
  summary="NO-FAILURES ($pending_count pending)"
else
  summary="ALL-CHECKS-PASS"
fi
echo "== $summary =="
exit "$fail"
