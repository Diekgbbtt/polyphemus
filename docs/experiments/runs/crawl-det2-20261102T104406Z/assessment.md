# steel_crawl prototype v2 assessment

- Run: `docs/experiments/runs/crawl-det2-20261102T104406Z`
- Pages: 7
- Actions: 60
- Forms: 1 attempted / 1 succeeded
- Fields: 5/5 filled (1.0)
- Network fields: 5/5 (1.0)
- Removed: 39 (unsafe 39, safe 0)
- XHR/Fetch: 87 captured, 87 with response, 87 with body
- Endpoints: 26 observed, 2 declared

## Invariants

| Invariant | Result |
| - | - |
| `auth_precondition_authenticated` | PASS |
| `unsafe_actions_executed_zero` | PASS |
| `anonymous_api_requests_zero` | PASS |
| `manifest_v2_keys` | PASS |
| `crawl_unsafe_endpoints_zero` | FAIL |
| `bootstrap_unsafe_flows_isolated` | PASS |
| `declared_unsafe_not_observed` | PASS |
| `form_success` | PASS |
| `xhr_response_complete` | PASS |

## Forms

| Submit | Synthetic | Success | HTTP | Declared method | Observed method | URL |
| - | - | - | - | - | - | - |
| 注册 | False | True | 200 | GET | POST | http://172.20.0.1:49017/api/register |

## Safety

| Type | Name | Truth | Source |
| - | - | - | - |
| BUTTON | 批量添加用户 | auth_state | guard |
| BUTTON | 批量删除 | destruction | guard |
| BUTTON | 添加角色 | auth_state | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 批量删除 | destruction | guard |
| FORM | 角色名 角色描述 功能配置 用户管理 角色管理 内容管理 菜单配置 首页 用户管理 内容管理 系统配置 | auth_state | guard |
| FORM | 确 定 | auth_state | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 批量删除 | destruction | guard |
| BUTTON | 批量删除 | destruction | guard |

## Boundary

- Observed crawl unsafe endpoints: 2
- Declared unsafe endpoints: 0
- Bootstrap unsafe flows (outside crawl): 1
- Crawl unsafe flows: 2

## Phase capture

- {'bootstrap': 56, 'oracle': 1, 'crawl': 319}

