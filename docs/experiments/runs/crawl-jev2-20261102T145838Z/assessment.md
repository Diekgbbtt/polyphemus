# steel_crawl prototype v2 assessment

- Run: `docs/experiments/runs/crawl-jev2-20261102T145838Z`
- Pages: 6
- Actions: 20
- Forms: 0 attempted / 0 succeeded
- Fields: 0/0 filled (None)
- Network fields: 0/0 (None)
- Removed: 36 (unsafe 36, safe 0)
- XHR/Fetch: 39 captured, 39 with response, 39 with body
- Endpoints: 20 observed, 0 declared

## Invariants

| Invariant | Result |
| - | - |
| `auth_precondition_authenticated` | PASS |
| `unsafe_actions_executed_zero` | PASS |
| `anonymous_api_requests_zero` | PASS |
| `manifest_v2_keys` | PASS |
| `crawl_unsafe_endpoints_zero` | PASS |
| `bootstrap_unsafe_flows_isolated` | PASS |
| `declared_unsafe_not_observed` | PASS |
| `form_success` | n/a |
| `xhr_response_complete` | PASS |

## Forms

| Submit | Synthetic | Success | HTTP | Declared method | Observed method | URL |
| - | - | - | - | - | - | - |

## Safety

| Type | Name | Truth | Source |
| - | - | - | - |
| BUTTON | 批量删除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 添加角色 | auth_state | guard |
| BUTTON | 批量删除 | destruction | jev |
| BUTTON | 批量添加用户 | auth_state | guard |
| BUTTON | 批量删除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |
| BUTTON | 移除 | destruction | jev |

## Boundary

- Observed crawl unsafe endpoints: 0
- Declared unsafe endpoints: 0
- Bootstrap unsafe flows (outside crawl): 1
- Crawl unsafe flows: 0

## Phase capture

- {'bootstrap': 56, 'oracle': 1, 'crawl': 148}

