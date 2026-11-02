# Steel crawl prototype v2

- Run: `crawl-jev1-20261102T144953Z`
- Session: `steel-jev1-20261102T144953Z`
- Target: `http://172.20.0.1:49017`
- Stop: `action_budget`
- Auth: `authenticated` (legacy_surface_gate)
- Pages: 6
- Actions: 60
- Forms attempted / succeeded: 3 / 3
- Flows: 366 (XHR/Fetch 21)
- Endpoints: 26
- Parameters: 11
- Scripts: 13
- Removed: 4
- Jev calls: 122 (errors 0)
- Errors: 0

## Quality

- Impact order compliance: 0.9666666666666667
- Form success rate: 1.0
- Field coverage: 1.0
- XHR capture rate: 1.0
- Safety recall: 1.0
- Unsafe actions executed: 0
- Anonymous API requests: 0

## Pages

- http://172.20.0.1:49017/index | 白卷 - White Jotter | depth 0 | from seed
- http://172.20.0.1:49017/register | 白卷 - White Jotter | depth 1 | from extra_seed
- http://172.20.0.1:49017/jotter | 白卷 - White Jotter | depth 1 | from action
- http://172.20.0.1:49017/library | 白卷 - White Jotter | depth 2 | from action
- http://172.20.0.1:49017/admin/dashboard | 白卷 - White Jotter | depth 3 | from action
- http://172.20.0.1:49017/admin/user/profile | 白卷 - White Jotter | depth 4 | from action

## Forms

- 搜索 | synthetic=True | success=True | http=200 | http://172.20.0.1:49017/api/search?keywords=test
- 搜索 | synthetic=True | success=True | http=200 | http://172.20.0.1:49017/api/search?keywords=test
- 搜索 | synthetic=True | success=True | http=200 | http://172.20.0.1:49017/api/search?keywords=test

## Removed

- FORM `注册` | truth=safe | source=jev
- CUSTOM `奢侈与逸乐 [英]马克辛·伯格 / 2019-3 / 中国工人出版社 本书探讨了十八世纪英国新式、时尚的消费品的发明、制造和购买。` | truth=payment | source=guard
- BUTTON `批量删除` | truth=destruction | source=jev
- BUTTON `批量添加用户` | truth=auth_state | source=guard

## Errors

