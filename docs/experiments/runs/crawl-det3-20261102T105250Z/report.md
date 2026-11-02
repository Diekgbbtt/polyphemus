# Steel crawl prototype v2

- Run: `crawl-det3-20261102T105250Z`
- Session: `steel-det3-20261102T105250Z`
- Target: `http://172.20.0.1:49017`
- Stop: `action_budget`
- Auth: `authenticated` (legacy_surface_gate)
- Pages: 5
- Actions: 50
- Forms attempted / succeeded: 1 / 1
- Flows: 251 (XHR/Fetch 12)
- Endpoints: 20
- Parameters: 9
- Scripts: 12
- Removed: 1
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
- http://172.20.0.1:49017/jotter | 白卷 - White Jotter | depth 1 | from action
- http://172.20.0.1:49017/library | 白卷 - White Jotter | depth 2 | from action

## Forms

- 注册 | synthetic=False | success=True | http=200 | http://172.20.0.1:49017/api/register

## Removed

- CUSTOM `奢侈与逸乐 [英]马克辛·伯格 / 2019-3 / 中国工人出版社 本书探讨了十八世纪英国新式、时尚的消费品的发明、制造和购买。` | truth=payment | source=guard

## Errors

