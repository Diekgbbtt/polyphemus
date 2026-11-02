# Steel crawl prototype v2

- Run: `crawl-det2-20261102T104406Z`
- Session: `steel-det2-20261102T104406Z`
- Target: `http://172.20.0.1:49017`
- Stop: `action_budget`
- Auth: `authenticated` (legacy_surface_gate)
- Pages: 7
- Actions: 60
- Forms attempted / succeeded: 1 / 1
- Flows: 376 (XHR/Fetch 87)
- Endpoints: 28
- Parameters: 23
- Scripts: 12
- Removed: 39
- Jev calls: 0 (errors 0)
- Errors: 0

## Quality

- Impact order compliance: 1.0
- Form success rate: 1.0
- Field coverage: 1.0
- XHR capture rate: 1.0
- Safety recall: 1.0
- Unsafe actions executed: 0
- Anonymous API requests: 0

## Pages

- http://172.20.0.1:49017/index | 白卷 - White Jotter | depth 0 | from seed
- http://172.20.0.1:49017/register | 白卷 - White Jotter | depth 1 | from extra_seed
- http://172.20.0.1:49017/admin/dashboard | 白卷 - White Jotter | depth 2 | from action
- http://172.20.0.1:49017/admin/user/profile | 白卷 - White Jotter | depth 3 | from action
- http://172.20.0.1:49017/admin/user/role | 白卷 - White Jotter | depth 4 | from action
- http://172.20.0.1:49017/admin/content/book | 白卷 - White Jotter | depth 4 | from action
- http://172.20.0.1:49017/admin/content/banner | 白卷 - White Jotter | depth 5 | from action

## Forms

- 注册 | synthetic=False | success=True | http=200 | http://172.20.0.1:49017/api/register

## Removed

- BUTTON `批量添加用户` | truth=auth_state | source=guard
- BUTTON `批量删除` | truth=destruction | source=guard
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
- FORM `角色名 角色描述 功能配置 用户管理 角色管理 内容管理 菜单配置 首页 用户管理 内容管理 系统配置` | truth=auth_state | source=guard
- FORM `确 定` | truth=auth_state | source=guard
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

