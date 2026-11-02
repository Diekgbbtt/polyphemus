# steel_crawl prototype v2 assessment

- Run: `docs/experiments/runs/crawl-det1-20261102T104039Z`
- Pages: 0
- Actions: 0
- Forms: 1 attempted / 1 succeeded
- Fields: 0/5 filled (0.0)
- Network fields: 5/5 (1.0)
- Removed: [{'type': 'BUTTON', 'name': '批量删除', 'truth': 'destruction', 'source': 'guard'}, {'type': 'BUTTON', 'name': '移除', 'truth': 'destruction', 'source': 'guard'}, {'type': 'BUTTON', 'name': '批量删除', 'truth': 'destruction', 'source': 'guard'}] (unsafe 3, safe 0)
- XHR/Fetch: 0 captured, 0 with response, 0 with body
- Endpoints: 0 observed, 0 declared

## Invariants

| Invariant | Result |
| - | - |
| `auth_precondition_authenticated` | FAIL |
| `unsafe_actions_executed_zero` | PASS |
| `anonymous_api_requests_zero` | FAIL |
| `manifest_v2_keys` | FAIL |
| `crawl_unsafe_endpoints_zero` | PASS |
| `bootstrap_unsafe_flows_isolated` | PASS |
| `declared_unsafe_not_observed` | PASS |
| `form_success` | PASS |
| `xhr_response_complete` | n/a |

## Forms

| Submit | Synthetic | Success | HTTP | Declared method | Observed method | URL |
| - | - | - | - | - | - | - |
| 注册 | False | True | 200 | GET | POST | http://172.20.0.1:49017/api/register |

## Safety

| Type | Name | Truth | Source |
| - | - | - | - |
| BUTTON | 批量删除 | destruction | guard |
| BUTTON | 移除 | destruction | guard |
| BUTTON | 批量删除 | destruction | guard |

## Boundary

- Observed crawl unsafe endpoints: 0
- Declared unsafe endpoints: 0
- Bootstrap unsafe flows (outside crawl): 0
- Crawl unsafe flows: 0

## Phase capture

- {}

