# Steel crawl prototype v2

- Run: `crawl-det4-20261102T105859Z`
- Session: `steel-det4-20261102T105859Z`
- Target: `http://172.20.0.1:49017`
- Stop: `action_budget`
- Auth: `authenticated` (legacy_surface_gate)
- Pages: 6
- Actions: 20
- Forms attempted / succeeded: 0 / 0
- Flows: 256 (XHR/Fetch 50)
- Endpoints: 21
- Parameters: 0
- Scripts: 11
- Removed: 37
- Jev calls: 0 (errors 0)
- Errors: 0

## Quality

- Impact order compliance: 1.0
- Form success rate: None
- Field coverage: None
- XHR capture rate: 1.0
- Safety recall: 1.0
- Unsafe actions executed: 0
- Anonymous API requests: 0

## Pages

- http://172.20.0.1:49017/index | 白卷 - White Jotter | depth 0 | from seed
- http://172.20.0.1:49017/admin/user/role | 白卷 - White Jotter | depth 1 | from extra_seed
- http://172.20.0.1:49017/admin/user/profile | 白卷 - White Jotter | depth 2 | from action
- http://172.20.0.1:49017/admin/dashboard | 白卷 - White Jotter | depth 3 | from action
- http://172.20.0.1:49017/admin/content/book | 白卷 - White Jotter | depth 4 | from action
- http://172.20.0.1:49017/admin/content/banner | 白卷 - White Jotter | depth 5 | from action

## Forms


## Removed

- BUTTON `添加角色` | truth=auth_state | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `批量删除` | truth=destruction | source=guard
- BUTTON `批量添加用户` | truth=auth_state | source=guard
- BUTTON `批量删除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `移除` | truth=destruction | source=guard
- BUTTON `批量删除` | truth=destruction | source=guard
- BUTTON `批量删除` | truth=destruction | source=guard

## Errors

