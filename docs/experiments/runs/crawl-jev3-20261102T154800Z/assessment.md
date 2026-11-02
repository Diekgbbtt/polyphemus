# steel_crawl prototype v2 assessment

- Run: `docs/experiments/runs/crawl-jev3-20261102T154800Z`
- Pages: 7
- Actions: 59
- Forms: 1 attempted / 1 succeeded
- Fields: 5/5 filled (1.0)
- Network field match (diagnostic): 5/5 (1.0)
- Removed by Jev: 35 (manual labels: unsafe None, safe None)
- XHR/Fetch: 73 captured, 73 with response, 73 with body
- No-op local-state rate: 0.5102040816326531
- No-op all-actions rate: 0.423728813559322
- Endpoints: 24 observed, 0 declared

## Invariants

| Invariant | Result |
| - | - |
| `auth_precondition_authenticated` | PASS |
| `unsafe_actions_executed_zero` | n/a |
| `anonymous_api_requests_zero` | PASS |
| `manifest_v2_keys` | PASS |
| `crawl_unsafe_endpoints_zero` | PASS |
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
| BUTTON | 批量删除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 批量删除 | None | jev |
| BUTTON | 批量删除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 移除 | None | jev |
| BUTTON | 批量删除 | None | jev |

## Boundary

- Observed crawl unsafe endpoints: 0
- Declared unsafe endpoints: 0
- Bootstrap unsafe flows (outside crawl): 1
- Crawl unsafe flows: 0

## Phase capture

- {'bootstrap': 56, 'oracle': 1, 'crawl': 286}

