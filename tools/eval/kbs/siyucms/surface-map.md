# SIYUCMS (6.1) - reverse-engineered endpoint inventory

Source of truth: `~/WebExploitBench/siyucms/setup_files/codebase/siyucms/` (app
source), the Dockerfile build steps, the applied patches, and the seed SQL
mounted at `/docker-entrypoint-initdb.d/01-siyucms.sql`. Deployment: Apache
serving `public/`, PHP 7.3, MySQL 5.7 database `tp6`, table prefix `tp_`.

## Routing model

- ThinkPHP multi-app: the first URL segment selects the app
  (`/index`, `/mobile`, `/admin`, `/api`); empty path dispatches to the default
  app `index`.
- `url_html_suffix = html`; `.html` suffixes are accepted on routes.
- `url_route_must = false`: controllers are reachable by the classic
  `/<app>/<controller>/<action>` convention even without an explicit route.
- The front apps register a dynamic route per category that has a folder set:
  `GET /<cate_folder>` and `GET /<cate_folder>/<id>` (id numeric), plus
  `tag_<module>/<t>`.
- Controllers without a matching class fall through to the `Error` empty
  controller, which serves generic module listing/detail.
- Debug mode is enabled in `.env` (`APP_DEBUG=true`, database `DEBUG=true`).
- Admin login captcha is disabled at boot by the entrypoint
  (`UPDATE tp_system SET code = 0 WHERE id = 1`); front form captcha
  (`message_code`) is 0 in the seed.

## Response conventions

- Front/admin HTML pages render templates; ajax/json responses are used by the
  admin UI (`{error, msg, url, ...}`).
- api app responses are always JSON: `{"code":int,"msg":string,"time":int,"data":...}`
  with `code=1` success (note: the api profile-update action returns `code=0`
  on success).

## Front site - index app (public website)

### Home page
- GET `/` , GET `/index/index`
- Renders the theme home template; may redirect to the mobile app when the
  mobile switch is on and the client is a mobile device.
- role: public

### Search
- GET `/index/search` (param `search`)
- Renders the theme search template for the keyword.
- role: public

### Tag
- GET `/index/tag` (params `t`, `module`)
- Registered route: `GET tag_<module>/<t>`
- Renders the theme tag template.
- role: public

### Message submission
- POST `/index/add`
- Posts form fields of the target content module (captcha and required-field
  checks per system settings); inserts a record with status 0; optional email
  notification. Excluded from request caching.
- role: public

### Captcha
- GET `/index/captcha`
- Returns a captcha image (think-captcha).
- role: public

### Category listing (dynamic + generic)
- GET `/<cate_folder>` for categories with a folder (e.g. from seed:
  `about`, `introduction`, `culture`, `news`, `information`, `honours`,
  `product`, `download`, `team`, `contact`)
- GET `/<module>/index` for folder-less categories (params `cate`)
  (module in {article, page, picture, product, download, team, message})
- Renders the category's list template; single-page modules render their page
  content with reading-permission gating.
- role: public

### Content detail (dynamic + generic)
- GET `/<cate_folder>/<id>` (id numeric) for categories with a folder
- GET `/<module>/info` (params `cate`, `id`) for folder-less categories
- Increments the hit counter, applies the record's reading-permission check,
  honors an external jump url, renders the detail template.
- role: public

## Front site - mobile app

Same controller families as the index app, under the `/mobile` app prefix:
- GET `/mobile/index/index`, `/mobile/index/search`, `/mobile/index/tag`,
  `/mobile/index/add`, `/mobile/index/captcha`
- Dynamic category routes are registered inside the mobile app too
  (`/mobile/<cate_folder>`, `/mobile/<cate_folder>/<id>`).
- role: public

## Member center - index and mobile apps

### Member login
- GET `/user/login` (page), POST `/user/login` (submit; params `username`,
  `password`, optional `message_code`, `callback`)
- GET `/mobile/user/login`, POST `/mobile/user/login`
- Opens the member web session (`user` key); redirects on success to the
  callback target.
- role: public

### Member registration
- GET `/user/register` (page), POST `/user/register` (submit; params `email`,
  `password`, `password2`, optional `message_code`, `sex`)
- GET `/mobile/user/register`, POST `/mobile/user/register`
- role: public

### Member center home
- GET `/user/index`, GET `/mobile/user/index`
- Requires member session; shows the member's profile.
- role: authenticated (member session)

### Member settings
- GET `/user/set` (page), POST `/user/set` (submit)
- POST with `password` + `password2` runs password change (also `nowpassword`);
  otherwise updates `sex`, `qq`, `mobile` (mobile uniqueness enforced).
- GET `/mobile/user/set`, POST `/mobile/user/set`
- role: authenticated (member session)

### Member logout
- GET `/user/logout`, GET `/mobile/user/logout`
- role: authenticated (member session)

## Back office - admin app

All admin controllers sit behind the admin middleware: a missing admin session
redirects to the login page. The open allowlist (no permission check, session
still required) covers `Index/index`, `Index/clear`, `Index/preview`,
`Index/select2`, `Upload/index` and the Login controller. All other actions are
rule-checked unless the administrator is the super administrator (id 1).
Every admin request is written to the operation log.

### Admin login
- GET `/admin/login/index` (page), GET `/admin/login/captcha` (image),
  GET `/admin/login/logout`
- POST `/admin/login/checkLogin` (params `username`, `password`, `vercode`
  when captcha enabled, `__token__`)
- Response JSON `{error:0, href, msg}` on success; `error` 1 or 2 on failure.
- role: public

### Dashboard and utilities
- GET `/admin/index/index` - dashboard (server, PHP, MySQL versions; recent
  member and message counts)
- POST `/admin/index/clear` - clears the runtime cache and logs out
- GET `/admin/index/preview` (params `module`, `id`) - redirects to the public
  record page
- GET `/admin/index/select2` (params `id`, `keyWord`, `rows`, `value`) - ajax
  data feed for relation select fields
- GET `/admin/index/linkage` (params `model`, `key`, `keyValue`, `pid`,
  `pidFieldName`) - ajax linkage data feed
- role: authenticated (admin); first four are on the open allowlist, linkage
  is rule-checked.

### Generic CRUD module actions
For each managed table the standard actions exist on
`/admin/<controller>/...`:
- `index` (list page; `getList=1` returns paginated json), `add` (form),
  `addPost` (POST save), `edit/<id>` (form), `editPost` (POST save), `del/<id>`
  (POST delete; comma-separated ids trigger batch), `selectDel/<id>` (POST batch
  delete), `sort` (POST reorder), `state/<id>` (POST toggle), `export` (data
  export).
- Controllers exposing the generic set: `Admin`, `AdminLog`, `Ad`, `AdType`,
  `Article`, `Debris`, `Dictionary`, `DictionaryType`, `Download`, `FieldGroup`,
  `Link`, `Message`, `Page`, `Picture`, `Product`, `Team`, `Users`, `UsersType`,
  `System`, `Cate` (list/add/addPost/edit/editPost/del + batchAdd/batchAddPost).
- role: authenticated (admin), rule-checked.

### Administrator management
- `/admin/admin/index`, `add`, `addPost` (params include `group_id`, `password`),
  `edit/<id>`, `editPost`, `del/<id>`, `selectDel/<id>`
- Super administrator (id 1) cannot be deleted.
- role: authenticated (admin), rule-checked.

### Role groups and menu rules
- `/admin/authGroup/index`, `access/<id>` (permission tree page), `accessPost`
  (POST; params `rules`, `id`)
- `/admin/authRule/index`, `add/<pid>`, `edit/<id>` (inherits generic
  addPost/editPost/del)
- role: authenticated (admin), rule-checked.

### System settings
- `/admin/system/index`, `edit/1`, `editPost` (single-record table `system`)
- Fields cover site identity, contact, SEO, mobile switch, captcha switches,
  template selection, upload limits/driver.
- role: authenticated (admin), rule-checked.

### Mail and SMS configuration
- GET `/admin/config/email` (form), POST `/admin/config/emailPost`,
  POST `/admin/config/emailSend` (param `email`)
- GET `/admin/config/sms` (form), POST `/admin/config/smsPost`,
  POST `/admin/config/smsSend` (uses Alibaba Cloud Dysmsapi)
- role: authenticated (admin), rule-checked.

### Database maintenance
- GET `/admin/database/database` (table list; `getList=1` returns json)
- POST `/admin/database/backup` (param `id`, comma-separated table names)
- POST `/admin/database/optimize` (param `id`)
- POST `/admin/database/repair` (param `id`)
- GET `/admin/database/restore` (backup file list)
- POST `/admin/database/import/<id>` (restore)
- GET `/admin/database/downFile/<id>` (download backup)
- POST `/admin/database/del/<id>` (delete backup file)
- Backups live in the Data directory.
- role: authenticated (admin), rule-checked.

### Module and field management
- `/admin/module/index`, `add`, `addPost` (creates the module's table),
  `edit/<id>`, `editPost` (may rename table/primary key), `del/<id>`,
  `selectDel/<id>`, `checkTale` (param `table_name`, json table inspection),
  `build/<id>` (generate controller code), `makeRule/<id>` (generate menu rules)
- `/admin/field/index`, `add` (param `moduleId`), `changeType` (ajax field
  config), `addPost`, `edit/<id>`, `editPost` (param `execute_sql`),
  `state/<id>` (param `field`), `del/<id>`, `selectDel/<id>` - alter the
  underlying table columns
- `/admin/fieldGroup/index` (generic CRUD)
- role: authenticated (admin), rule-checked.

### Dictionaries
- `/admin/dictionaryType/index` and `/admin/dictionary/index` (generic CRUD)
- role: authenticated (admin), rule-checked.

### Categories
- `/admin/cate/index` (tree list), `add/<parentId>`, `addPost`, `edit/<id>`,
  `editPost`, `del/<id>` (cascades to children and their content),
  `batchAdd` (multi-row form), `batchAddPost`
- role: authenticated (admin), rule-checked.

### Template management
- GET `/admin/template/index` (param `type` html|css|js; `getList=1` json file
  list), `add` (form), POST `addPost` (params `filename`, `type`, `content`),
  `edit/<id>` (param `type`), POST `editPost` (params `filename`, `type`,
  `content`; writes a backup copy when the backup switch is on),
  `del/<id>` (param `type`), `selectDel/<id>`, POST `del` - theme files under
  the template directory
- GET `/admin/template/img` (param `folder`; media browser for the theme image
  directory)
- POST `/admin/template/imgDel` (params `folder`, `filename`) - deletes the
  named file (or directory) under the theme image path; folder and filename are
  taken from the request and used to compose the target path.
- role: authenticated (admin), rule-checked.

### Uploads and ueditor
- `/admin/upload/index` is on the open allowlist (session required).
  Behaviour selected by params:
  - `from=ckeditor` - uploads posted file fields, returns `{uploaded, url}`,
    `responseType=json` returns a single url
  - `from=ueditor` - dispatches on `action`:
    - `config` - returns the ueditor config json
    - `upload_image`, `upload_video`, `upload_file` - chunked upload
    - `list_image`, `list_file` - paginated file list under uploads
      (params `start`, `size`)
    - `catch_image` - remote image catcher: posts `file` as a list of remote
      http(s) image urls; each url is fetched server-side (desktop user-agent,
      no redirect following, short timeout) and the response bytes are written
      under `uploads/<YYYYMMDD>/`; returns `{state, list, fail_list}`.
  - default - chunked large-file upload (params `chunk`, `chunks`, `name`;
    writes reassembled file under `uploads/<YYYYMMDD>/`).
  - Upload validation restricts extensions/sizes from system settings (image
    vs file groups; the php/asp suffixes are stripped from the configured
    extension lists).
- role: authenticated (admin).

### Plugins
- `/admin/plugin/index` (list; `getList=1` json), `config`, `configSave`,
  `state/<id>`, `install`, `uninstall`
- role: authenticated (admin), rule-checked.

### Demo pages
- `/admin/demo/button`, `icons`, `general`, `modals`, `timeline`, `layer`,
  `layerForm` (UI kit demo pages), POST `addPost` (demo form submit)
- role: authenticated (admin), rule-checked.

## Member api - api app

All `/api/user/*` actions are POST per the apidoc; the api middleware requires a
valid `token` header for every action except login and register. Token: JWT
HS256, issuer `api.siyucms.com`, audience `siyucms_app`, 1-hour expiry,
member id in the `uid` claim. Responses are the JSON envelope
`{code, msg, time, data}`.

### Member login
- POST `/api/user/login` (params `username`, `password`)
- `username` matches member `email` or `mobile`; password compared as md5.
- Returns `{code:1, msg:"登录成功", data:{token}}`; disabled members rejected.
- role: public

### Member registration
- POST `/api/user/register` (params `email`, `password`, optional `sex`)
- Password length >= 6, email format and uniqueness enforced; assigns default
  member type.
- role: public

### Member profile view
- POST `/api/user/index` (header `token`)
- Returns the authenticated member's record joined with `type_name`.
- role: authenticated (jwt)

### Member password change
- POST `/api/user/editPwd` (header `token`; params `oldPassword`, `newPassword`)
- role: authenticated (jwt)

### Member profile update
- POST `/api/user/editInfo` (header `token`; params `sex`, `qq`, `mobile`,
  optional `id`)
- Updates the profile identified by the `id` parameter, defaulting to the
  authenticated token subject when absent; mobile uniqueness enforced.
- role: authenticated (jwt)

## Static and auxiliary surface

- `public/` document root serves static assets (`/static/...`,
  `/uploads/...`, `/template/...`).
- `/index.php` is the front controller.
- Runtime and Data directories are written by the application.
- The think console binary (`/think`) exists but is not exposed over HTTP.