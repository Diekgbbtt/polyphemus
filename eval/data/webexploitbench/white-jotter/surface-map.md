# White-Jotter surface map

Reverse-engineered endpoint inventory of the deployed application at the pinned
version. Reconstructed from the deployed checkout artifacts plus the upstream
source at the pin; see `research-notes.md` for the source ledger and version pin.

## Deployment shape

- Single application service `wj`, a Spring Boot 2.1 WAR running on the embedded
  Tomcat, listening on port 8443 (http).
- The same origin serves the built Vue.js single-page application from static
  resources; client-side routing falls back to the SPA index for unknown paths.
- The frontend axios client uses `/api` as its base URL and sends credentials
  (cookies) with every request.
- Backing services: MySQL (database `wj`) and Redis, both wired via environment
  variables at container start.
- Response body envelope for all JSON endpoints: `{"code": 200|400|401|404|500,
  "message": "<string>", "result": <object|null>}`. Successes carry `code: 200`
  and a Chinese success message; failures carry `code: 400` with a reason.
- gzip compression is enabled for JSON, XML, HTML and JS responses over 1KB.
- CORS is configured to allow one fixed origin (`http://localhost:8080`) with
  credentials; in this deployment the frontend is same-origin, so CORS headers
  are not part of normal traffic.

## Authentication model (as deployed)

- Apache Shiro filter chain:
  - `/api/authentication` -> `authc`
  - `/api/menu` -> `authc`
  - `/api/admin/**` -> custom path-matching filter (the later chain entry
    overrides the earlier `authc` entry for the same pattern).
- The custom filter requires an authenticated subject for every admin path, then
  checks the requested API against the permission URLs granted to the subject's
  roles by prefix matching (recorded in `admin_permission`, joined through
  `admin_role_permission` and `admin_user_role`).
- Seeded permission prefixes (URL prefixes that trigger the permission check):
  - `/api/admin/user` (users_management)
  - `/api/admin/role` (roles_management)
  - `/api/admin/content` (content_management)
- Unauthenticated or unauthorized admin/`authc` requests are refused with a
  redirect to `/nowhere` (the configured login URL); the SPA treats a failed
  request as sign-out.
- Sign-in uses salted (16-byte random salt) MD5 hashing with two iterations.
- A `rememberMe` cookie is issued on sign-in (3-day lifetime) so the identity
  persists across sessions.

## Endpoint inventory

### Sign-in, sign-out, registration (LoginController)

`POST /api/login`
- Body: `{"username": "<string>", "password": "<string>"}` (JSON user object;
  other fields ignored).
- Username is html-escaped before use.
- On success: `Result` with `result` = the username string; sets the
  remember-me cookie and a session.
- On failure: `code: 400`, message one of "密码错误" (wrong password),
  "账号不存在" (unknown account), "该用户已被禁用" (account disabled).
- Exposure: public.

`POST /api/register`
- Body: `{"username": "<string>", "password": "<string>", "name": "...",
  "phone": "...", "email": "...", "roles": [{"id": <int>}]}`.
- Creates the account (html-escaped profile fields, random salt, hashed
  password, enabled by default) and, when a non-empty roles list is present,
  binds those roles to the new account.
- Response: `code: 200` "注册成功" on success; `code: 400` for empty
  credentials or an existing username.
- Exposure: public.

`GET /api/logout`
- Ends the subject's session.
- Response: `Result` "成功登出".
- Exposure: public.

`GET /api/authentication`
- Reports the authentication status of the request.
- Response: plain text "身份认证成功".
- Exposure: authenticated (`authc`).

### User management (UserController)

`GET /api/admin/user`
- Lists all accounts.
- Response: `result` = array of user DTOs:
  `{"id", "username", "name", "phone", "email", "enabled",
  "roles": [{"id", "name", "nameZh", "enabled"}]}`.
- Requires: authenticated + `/api/admin/user` permission.

`PUT /api/admin/user/status`
- Body: `{"username": "<string>", "enabled": <bool>}`.
- Flips the account's enabled flag.
- Response: `Result` "用户状态更新成功".
- Requires: authenticated + `/api/admin/user` permission.

`PUT /api/admin/user/password`
- Body: `{"username": "<string>"}`.
- Resets the account password to the fixed default "123" with a new salt.
- Response: `Result` "重置密码成功".
- Requires: authenticated + `/api/admin/user` permission.

`PUT /api/admin/user`
- Body: `{"username": "<string>", "name": "...", "phone": "...", "email":
  "...", "roles": [{"id": <int>}]}`.
- Updates the profile fields and rebinds the account's roles.
- Response: `Result` "修改用户信息成功".
- Requires: authenticated + `/api/admin/user` permission.

### Menu provisioning (MenuController)

`GET /api/menu`
- Returns the navigation menu tree for the current user.
- Response: `result` = array of menu nodes:
  `{"id", "path", "name", "nameZh", "iconCls", "component", "parentId",
  "children": [...]}`; only top-level nodes are returned, children nested.
- Exposure: authenticated (`authc`).

`GET /api/admin/role/menu`
- Returns the menu tree for a fixed role (role id 1) used by the role editor.
- Response: same menu-node shape as above.
- Requires: authenticated + `/api/admin/role` permission (prefix match).

### Role and permission management (RoleController)

`GET /api/admin/role`
- Lists roles with their permissions and menus.
- Response: `result` = array of
  `{"id", "name", "nameZh", "enabled", "perms": [{"id", "name", "desc_",
  "url"}], "menus": [menu nodes]}`.
- Requires: authenticated + `/api/admin/role` permission.

`PUT /api/admin/role/status`
- Body: `{"id": <int>, "enabled": <bool>}`.
- Flips the role's enabled flag.
- Response: `Result` "用户<nameZh>状态更新成功".
- Requires: authenticated + `/api/admin/role` permission.

`PUT /api/admin/role`
- Body: `{"id": <int>, "name": "...", "nameZh": "...", "enabled": <bool>,
  "perms": [{"id": <int>}]}`.
- Updates the role record and rebinds the role's permission set.
- Response: `Result` "修改角色信息成功".
- Requires: authenticated + `/api/admin/role` permission.

`POST /api/admin/role`
- Body: `{"id"?: <int>, "name": "...", "nameZh": "...", "perms"?: [...]}`.
- Creates (or updates) the role and rebinds its permission set.
- Response: `Result` "修改用户成功".
- Requires: authenticated + `/api/admin/role` permission.

`GET /api/admin/role/perm`
- Lists the permission catalog.
- Response: `result` = array of `{"id", "name", "desc_", "url"}`.
- Requires: authenticated + `/api/admin/role` permission.

`PUT /api/admin/role/menu?rid=<int>`
- Body: `{"menusIds": [<int>, ...]}`.
- Rebinds the role's menu set (deletes previous bindings, inserts the
  submitted ids).
- Response: `Result` "更新成功".
- Requires: authenticated + `/api/admin/role` permission.

### Library / book catalog (LibraryController)

`GET /api/books`
- Lists the book catalog, newest first, from the Redis cache when warm.
- Response: `result` = array of books:
  `{"id", "title", "author", "date", "press", "abs", "cover",
  "category": {"id", "name"}}`.
- Exposure: public.

`GET /api/categories/{cid}/books`
- Lists the books of a category; `cid` of 0 returns the full catalog.
- Response: same book shape as above.
- Exposure: public.

`GET /api/search?keywords=<string>`
- Searches books whose title or author matches the keyword.
- An empty keyword returns the full catalog.
- Response: same book shape as above.
- Exposure: public.

`POST /api/admin/content/books`
- Body: book JSON (add when no id, update when id present):
  `{"id"?, "title", "author", "date", "press", "abs", "cover",
  "category": {"id", "name"}}`.
- Saves the record and invalidates the cached catalog.
- Response: `Result` "修改成功".
- Requires: authenticated + `/api/admin/content` permission (prefix match).

`POST /api/admin/content/books/delete`
- Body: `{"id": <int>}`.
- Deletes the book record and invalidates the cached catalog.
- Response: `Result` "删除成功".
- Requires: authenticated + `/api/admin/content` permission.

`POST /api/admin/content/books/covers`
- Multipart upload, form field `file`.
- Writes the image under the workspace image folder with a 6-char random
  prefix plus the last 4 characters of the original file name.
- Response: plain text body, the image URL
  `http://localhost:8443/api/file/<stored-name>` (empty string on error).
- Requires: authenticated + `/api/admin/content` permission.

`GET /api/file/**`
- Serves a stored cover image for inline display.
- The path after `/api/file/` is URL-decoded twice and joined to the configured
  upload directory.
- Response: raw file bytes, `Content-Type: application/octet-stream`,
  `Content-Disposition: inline; filename="<name>"`; 404 when the target is not
  a regular file.
- Exposure: public.

### Jotter articles (JotterController)

`POST api/admin/content/article`
- Body: article JSON:
  `{"id"?, "articleTitle", "articleContentHtml", "articleContentMd",
  "articleAbstract", "articleCover", "articleDate"}`.
- Saves the article and invalidates the cached article pages.
- Response: `Result` "保存成功".
- Requires: authenticated + `/api/admin/content` permission.

`GET /api/article/{size}/{page}`
- Lists articles newest first, paged; `page` is 1-based.
- Response: `result` = paging envelope
  `{"content": [articles], "totalElements", "pageNumber", "pageSize",
  "numberOfElements", "totalPages", ...}`.
- Exposure: public.

`GET /api/article/{id}`
- Returns a single article by identifier.
- Response: `result` = article object (shape above).
- Exposure: public.

`DELETE /api/admin/content/article/{id}`
- Deletes the article and invalidates the cached article pages.
- Response: `Result` "删除成功".
- Requires: authenticated + `/api/admin/content` permission.

### Static SPA

`GET /`
- Serves the built single-page application (`index.html` plus hashed bundles
  under `/static/`).
- Unknown paths (client-side routes and 404s) are served the SPA index via the
  registered 404 error page.

### Actuator management surface

`GET /actuator/**`
- Spring Boot Actuator endpoints: health, info, beans, mappings, configprops,
  metrics, loggers and others; the `env` endpoint is excluded.
- Not covered by the Shiro chain, so reachable without sign-in.
- `health` details are always shown.