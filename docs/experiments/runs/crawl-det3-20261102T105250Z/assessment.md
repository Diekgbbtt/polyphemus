# steel_crawl prototype v2 assessment

- Run: `docs/experiments/runs/crawl-det3-20261102T105250Z`
- Pages: 5
- Actions: 50
- Forms: 1 attempted / 1 succeeded
- Fields: 5/5 filled (1.0)
- Network fields: 5/5 (1.0)
- Removed: 1 (unsafe 1, safe 0)
- XHR/Fetch: 12 captured, 12 with response, 12 with body
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
| `form_success` | PASS |
| `xhr_response_complete` | PASS |

## Forms

| Submit | Synthetic | Success | HTTP | Declared method | Observed method | URL |
| - | - | - | - | - | - | - |
| 注册 | False | True | 200 | GET | POST | http://172.20.0.1:49017/api/register |

## Safety

| Type | Name | Truth | Source |
| - | - | - | - |
| CUSTOM | 奢侈与逸乐 [英]马克辛·伯格 / 2019-3 / 中国工人出版社 本书探讨了十八世纪英国新式、时尚的消费品的发明、制造和购买。 | payment | guard |

## Boundary

- Observed crawl unsafe endpoints: 0
- Declared unsafe endpoints: 0
- Bootstrap unsafe flows (outside crawl): 1
- Crawl unsafe flows: 0

## Phase capture

- {'bootstrap': 56, 'oracle': 1, 'crawl': 194}

