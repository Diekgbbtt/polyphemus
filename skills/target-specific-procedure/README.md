# target-specific-procedure

This branch holds the per-project procedures of the skill catalogue.

## Layout

```
skills/target-specific-procedure/<project_id>/<procedure>/SKILL.md
skills/target-specific-procedure/<project_id>/<procedure>/references/<name>.md
skills/target-specific-procedure/<project_id>/<procedure>/revisions/manifest.yaml
skills/target-specific-procedure/<project_id>/lessons/<skill>.yaml
skills/target-specific-procedure/<project_id>/evolution/<pass>.yaml
```

The branch is project data, not a shared skill.
A project owns its procedures: each project carries its own `authn` procedure, so a shared flat index would collide on the leaf name.
`SkillCatalogue` therefore never indexes this branch.
The project seam resolves the project bundle first, and the shared catalogue second.

## Writers

- The external authn bootstrapper writes the sign-in and sign-up procedures.
  The `meta/authn-skill-writing` skill is its authoring contract.
- The skill-evolution system writes the revised versions of the project's skills, and the newly mined project-specific skills.
  A revision keeps the bundle layout and appends one snapshot per published revision under `revisions/`.
- The lesson store appends one shard per skill under `lessons/`.
- The evolution launcher keeps one pass record per slot under `evolution/`.

## Loader rule

`SkillStore` roots the project area at `<skills_root>/target-specific-procedure/<project_id>/`.
`skill_for`, `list_skills`, `skill_meta`, `validate_skill`, and the L1 index middleware resolve the project bundle first when the caller passes a project scope.
An explicit catalogue mount still wins over the live root.

## Git tracking

The branch is runtime project data, not source.
`.gitignore` ignores everything under `target-specific-procedure/` except this README, so the topology stays visible while runtime writes never churn the working tree.
