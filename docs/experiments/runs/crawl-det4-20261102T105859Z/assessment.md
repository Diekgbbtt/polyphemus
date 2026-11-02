# steel_crawl prototype v2 assessment

- Run: `docs/experiments/runs/crawl-det4-20261102T105859Z`
- Pages: 6
- Actions: 20
- Forms: 0 attempted / 0 succeeded
- Fields: 0/0 filled (None)
- Network fields: 0/0 (None)
- Removed: 37 (unsafe 37, safe 0)
- XHR/Fetch: 50 captured, 50 with response, 50 with body
- Endpoints: 21 observed, 0 declared

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
| BUTTON | 批量添加用户 | auth_state | guard |
| BUTTON | 批量删除 | destruction | guard |
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

- Observed crawl unsafe endpoints: 0
- Declared unsafe endpoints: 0
- Bootstrap unsafe flows (outside crawl): 1
- Crawl unsafe flows: 0

## Phase capture

- {'bootstrap': 54, 'oracle': 3, 'crawl': 199}

