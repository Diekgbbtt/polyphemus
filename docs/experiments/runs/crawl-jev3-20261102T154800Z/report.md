# Steel crawl prototype v2

- Run: `crawl-jev3-20261102T154800Z`
- Session: `steel-jev3-20261102T154800Z`
- Target: `http://172.20.0.1:49017`
- Stop: `session_deadline`
- Auth: `authenticated` (legacy_surface_gate)
- Pages: 7
- Actions: 59
- Forms attempted / succeeded: 1 / 1
- Flows: 343 (XHR/Fetch 73)
- Endpoints: 24
- Parameters: 5
- Scripts: 12
- Removed: 35
- Jev calls: 153 (errors 0)
- Errors: 0

## Quality

- Impact order compliance: 1.0
- Form success rate: 1.0
- Field coverage: 1.0
- XHR capture rate: 1.0
- Jev removed: 35
- No-op local-state rate: 0.5102040816326531
- No-op all-actions rate: 0.423728813559322
- Anonymous API requests: 0

## Pages

- http://172.20.0.1:49017/index | 白卷 - White Jotter | depth 0 | from seed
- http://172.20.0.1:49017/admin/user/role | 白卷 - White Jotter | depth 1 | from extra_seed
- http://172.20.0.1:49017/register | 白卷 - White Jotter | depth 1 | from extra_seed
- http://172.20.0.1:49017/admin/dashboard | 白卷 - White Jotter | depth 2 | from action
- http://172.20.0.1:49017/admin/user/profile | 白卷 - White Jotter | depth 2 | from action
- http://172.20.0.1:49017/admin/content/book | 白卷 - White Jotter | depth 3 | from action
- http://172.20.0.1:49017/admin/content/banner | 白卷 - White Jotter | depth 4 | from action

## Forms

- 注册 | synthetic=False | success=True | http=200 | http://172.20.0.1:49017/api/register

## Removed

- BUTTON `批量删除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `批量删除` | source=jev
- BUTTON `批量删除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `移除` | source=jev
- BUTTON `批量删除` | source=jev

## Errors

