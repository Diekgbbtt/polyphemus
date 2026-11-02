# steel_crawl prototype v2 assessment

- Run: `docs/experiments/runs/crawl-jev1-20261102T144953Z`
- Pages: 6
- Actions: 60
- Forms: 3 attempted / 3 succeeded
- Fields: 6/6 filled (1.0)
- Network fields: 3/6 (0.5)
- Removed: 4 (unsafe 3, safe 1)
- XHR/Fetch: 21 captured, 21 with response, 21 with body
- Endpoints: 25 observed, 1 declared

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
| 搜索 | True | True | 200 |  | GET | http://172.20.0.1:49017/api/search?keywords=test |
| 搜索 | True | True | 200 |  | GET | http://172.20.0.1:49017/api/search?keywords=test |
| 搜索 | True | True | 200 |  | GET | http://172.20.0.1:49017/api/search?keywords=test |

## Safety

| Type | Name | Truth | Source |
| - | - | - | - |
| FORM | 注册 | safe | jev |
| CUSTOM | 奢侈与逸乐 [英]马克辛·伯格 / 2019-3 / 中国工人出版社 本书探讨了十八世纪英国新式、时尚的消费品的发明、制造和购买。 | payment | guard |
| BUTTON | 批量删除 | destruction | jev |
| BUTTON | 批量添加用户 | auth_state | guard |

## Boundary

- Observed crawl unsafe endpoints: 0
- Declared unsafe endpoints: 0
- Bootstrap unsafe flows (outside crawl): 1
- Crawl unsafe flows: 0

## Phase capture

- {'bootstrap': 56, 'oracle': 1, 'crawl': 309}

