# ComfyUI with ComfyUI-Manager - reverse-engineered endpoint inventory

Target: `http://comfyui-manager:8288` (host-exposed as `127.0.0.1:8288`).
Boot: `python main.py --listen 0.0.0.0 --port 8288 --cpu` (single user, no `--multi-user`,
no TLS, no authentication middleware).

## Global notes

- Every route defined in the main route table (core `server.py` handlers, the `app/`
  route modules, and ALL ComfyUI-Manager routes) is ALSO registered under an `/api`
  prefix. Example: `GET /prompt` and `GET /api/prompt` are equivalent; `POST
  /manager/queue/install` and `POST /api/manager/queue/install` are equivalent.
  Route defs registered directly on `PromptServer.instance.routes` (Manager, core)
  all get the mirror.
- Middleware: cache-control headers on js/css/images; origin-vs-host check only
  enforced when the Host is a loopback address (not applicable for the `comfyui-manager`
  hostname); no authentication. Max upload size from `--max-upload-size` (default 100MB).
- Static mounts: `/` serves the frontend package (`comfyui-frontend-package==1.32.10`),
  `/templates/{path:.*}` serves workflow template assets, `/docs` serves embedded docs,
  `/extensions/{name}/...` serves each custom node's web directory.
- Role on every route: public (no auth). The manager applies its own operator-policy
  gates (see security-policy notes under manager routes).

## Core - server.py

### WebSocket channel
- `GET /ws?clientId=<id>` -> websocket upgrade.
- Client sends JSON `{"type":"feature_flags","data":{...}}` as first message; server
  replies `{"type":"feature_flags","data":{...}}`.
- Server pushes events: `status` (queue info, `sid`), `executing` (node id),
  `progress`, `executing`/`executed`/`progress`/`cm-queue-status`, binary image
  previews (uint32 event + payload).
- On connect, server sends `status` with `{status:{exec_info:{queue_remaining}}, sid}`.

### Application entry
- `GET /` -> frontend `index.html` (`Cache-Control: no-cache`).

### Model inventory (folder listing)
- `GET /embeddings` -> JSON array of embedding names (extension stripped).
- `GET /models` -> JSON array of model folder type names.
- `GET /models/{folder}` -> JSON array of file paths under that model folder
  (404 if unknown folder). `{folder}` is matched against `folder_paths.folder_names_and_paths`.

### Extension listing
- `GET /extensions` -> JSON array of `/extensions/<name>/...` and relative js paths
  under the web root.

### Uploads
- `POST /upload/image` (multipart form) -> JSON `{"name","subfolder","type"}`.
  Fields: `image` (file), `type` (input|temp|output, default input), `subfolder`,
  `overwrite` (true|1 to skip duplicate handling). Duplicate detection by content
  hash; rejected (400) when the resolved path escapes the target directory.
- `POST /upload/mask` (multipart form) -> JSON same shape. Additional field
  `original_ref` (JSON `{"filename","type","subfolder"}`) naming the image the mask
  merges into; the alpha channel of the uploaded mask replaces the alpha of the
  referenced original and the merged PNG is saved.

### Asset viewing
- `GET /view?filename=<name>&type=<input|output|temp>&subfolder=<path>&channel=<rgba|rgb|a>&preview=<webp|jpeg>[;quality]`
  - `filename` may carry an annotation suffix (`[output]`/`[input]`/`[temp]`) that
    selects the base directory.
  - The subfolder value is normalized and containment-checked against the selected
    asset directory (403 on escape), then the original subfolder value is URL-decoded
    a second time and used to resolve the final file path; the file base name is used
    for the final lookup.
  - With `preview`: image is re-encoded to webp (or jpeg when allowed) at the given
    quality and served with `Content-Disposition: filename="..."`.
  - With `channel=rgb`/`a`: PNG with the requested channel.
  - Otherwise the file is served as-is; html/js/css mimetypes are forced to
    `application/octet-stream`.
  - 404 when file missing or parameter absent.
- `GET /view_metadata/{folder_name}?filename=<name>` -> JSON of the safetensors
  `__metadata__` block; only `.safetensors` filenames accepted (404 otherwise).

### Telemetry
- `GET /system_stats` -> JSON `{system:{os,ram_total,ram_free,comfyui_version,
  required_frontend_version,installed_templates_version,required_templates_version,
  python_version,pytorch_version,embedded_python,argv},devices:[{name,type,index,
  vram_total,vram_free,torch_vram_total,torch_vram_free}]}`.
- `GET /features` -> JSON of server feature flags.

### Prompt queue
- `GET /prompt` -> JSON `{exec_info:{queue_remaining}}`.
- `POST /prompt` (JSON body) -> `{prompt_id,number,node_errors}` (200) or
  `{error,node_errors}` (400 on invalid prompt / no prompt).
  Body: `{prompt:{<node_id>:{class_type,inputs,...}}, prompt_id?, client_id?,
  extra_data?, front?, number?, partial_execution_targets?}`. The graph is validated
  (`execution.validate_prompt`) before being queued; a `number` may be supplied to
  order the queue (negative `front` number inserts at the front).
- `GET /queue` -> JSON `{queue_running:[...],queue_pending:[...]}` (item tuples
  truncated to 5 fields).
- `POST /queue` (JSON `{clear:bool, delete:[prompt_id,...]}`) -> 200. Clears the
  queue and/or deletes pending items.
- `POST /interrupt` (JSON `{prompt_id?}`) -> 200. Global interrupt, or targeted
  interrupt of a running prompt by id.
- `POST /free` (JSON `{unload_models:bool, free_memory:bool}`) -> 200. Sets model
  unload / memory free flags for the next execution.

### History
- `GET /history?max_items=<n>&offset=<n>` -> JSON map prompt_id -> run record
  (prompt, outputs, status, metrics).
- `GET /history/{prompt_id}` -> JSON for that prompt only.
- `POST /history` (JSON `{clear:bool, delete:[prompt_id,...]}`) -> 200.

## Core - app modules

### User profiles
- `GET /users` -> JSON `{storage:"server",migrated:bool}` (single-user mode;
  in multi-user mode also `users`).
- `POST /users` (JSON `{username}`) -> JSON `user_id` (200) or `{error}` (400 on
  duplicate, empty, or reserved-prefix username). Single-user deployment has no
  registered users so registration fails; reserved prefix is `__`.

### Settings
- `GET /settings` -> JSON of the user settings object (from the settings file).
- `GET /settings/{id}` -> JSON value of that setting (null when absent).
- `POST /settings` (JSON object) -> 200. Merges new keys into the settings file.
- `POST /settings/{id}` (raw JSON body) -> 200. Sets that single key.

### User data files
- `GET /userdata?dir=<path>&recurse=<true>&full_info=<true>&split=<true>` ->
  JSON array of relative file paths under `<user>/<dir>` (400 no dir; 403 invalid
  dir; 404 missing dir). With `full_info`: array of `{path,size,modified,created}`;
  with `split`: array of `[path, ...components]`.
- `GET /v2/userdata?path=<rel>` -> JSON array of `{name,type(File|directory),path,
  size,modified}` entries, dirs first. (403 invalid user, 400 invalid path/not a
  dir, 404 missing, 500 on read error.)
- `GET /userdata/{file}` -> file bytes (`FileResponse`). Path may be URL-encoded.
- `POST /userdata/{file}?overwrite=<false>&full_info=<true>` (raw body) -> JSON
  relative path (or full info) on write (400 invalid name, 409 when overwrite=false
  and file exists, 403 outside user root).
- `DELETE /userdata/{file}` -> 204 (404 if missing).
- `POST /userdata/{file}/move/{dest}?overwrite=<false>&full_info=<true>` -> JSON
  result path (404 if source missing, 409 if dest exists and overwrite=false).

### Model inventory (experimental)
- `GET /experiment/models` -> JSON array `[{name,folders:[...]}]` over model folder
  types, excluding `configs` and `custom_nodes`.
- `GET /experiment/models/{folder}` -> JSON array of model file records
  `{name,pathIndex,modified,created,size}` (404 unknown folder).
- `GET /experiment/models/preview/{folder}/{path_index}/{filename:.*}` -> webp
  preview image for a model file (from a sibling image or safetensors cover images),
  404 when none.

### Custom node content
- `GET /workflow_templates` -> JSON map `{custom_node_dir:[workflow names]}`.
- `GET /i18n` -> JSON of merged translations from all custom nodes' `locales/`.
- `GET /global_subgraphs` -> JSON map id -> `{source,name,info}` (no file data).
- `GET /global_subgraphs/{id}` -> JSON entry incl. `data` (raw subgraph JSON).

## Internal subapp (frontend diagnostics)

Mounted at `/internal` (no `/api` mirror - separate subapp).
- `GET /internal/logs` -> text of concatenated log entries.
- `GET /internal/logs/raw` -> JSON `{entries:[{t,m,...}], size:{cols,rows}}`.
- `PATCH /internal/logs/subscribe` (JSON `{clientId,enabled}`) -> 200.
- `GET /internal/folder_paths` -> JSON map of folder type -> base path.
- `GET /internal/files/{directory_type}` -> JSON array of file names in that
  directory, newest first; `directory_type` limited to `output|input|temp` (400
  otherwise).

## ComfyUI-Manager (custom node, V3.37)

All manager routes are registered on the core route table and therefore ALSO live
under `/api`. None require authentication. Operator-policy gates: several manager
operations return 403 unless the `security_level` setting (seeded to `normal`) and
the listen address satisfy the manager's policy rules; the seeded `network_mode` is
`public`, `db_mode` is `cache`, `channel_url` is the default channel
(`https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main`), `update_policy`
is `stable-comfyui`, `component_policy` is `workflow`, `share_option` is `all`.

### Catalog queries
- `GET /customnode/getmappings?mode=<local|cache|remote|nickname>` -> JSON map of
  node -> node-pack mapping (with pattern-matched missing nodes).
- `GET /customnode/fetch_updates?mode=<...>` -> 200/201/400. Reloads and pulls the
  channel catalogs and fetches git state of custom node packs.
- `GET /customnode/getlist?mode=<...>&skip_update=<true>` -> JSON
  `{channel, node_packs:{...}}`; node pack entries carry `title`, `description`
  (markdown converted to HTML, tags sanitized), install state, version/update
  state, github stats and favorites.
- `GET /customnode/alternatives?mode=<...>` -> JSON map of alternative pack entries.
- `GET /customnode/installed?mode=<default|imported>` -> JSON map of installed
  node packs.
- `GET /customnode/versions/{node_name}` -> JSON of available versions (400 when
  unknown).
- `GET /customnode/disabled_versions/{node_name}` -> JSON of disabled versions
  (400 when none).
- `POST /customnode/import_fail_info` (JSON `{cnr_id|url}`) -> JSON of the recorded
  import failure info (400 when none).

### External model catalog
- `GET /externalmodel/getlist?mode=<...>` -> JSON model catalog; each model entry
  carries `installed` state plus `type`, `base`, `save_path`, `filename`, `url`,
  `description` (sanitized markdown).

### Work queue (manager background worker)
- `GET /manager/queue/status` -> JSON `{total_count,done_count,in_progress_count,
  is_processing}`.
- `GET /manager/queue/reset` -> 200. Replaces the queue with an empty one.
- `GET /manager/queue/start` -> 200 (201 if already running). Starts the worker
  thread; results are streamed as `cm-queue-status` websocket events.
- `POST /manager/queue/install` (JSON `{id,version,selected_version,channel,mode,
  files,pip,repository,ui_id,skip_post_install}`) -> 200 (403/404 on policy or
  resolution failures). Enqueues an install job. Catalog-membership risk scoring
  is applied before enqueueing.
- `POST /manager/queue/reinstall` (same body) -> 200. Uninstall then install.
- `POST /manager/queue/fix` (JSON `{id,version,files,ui_id}`) -> 200. Enqueues a
  fix job (reinstall from registry).
- `POST /manager/queue/uninstall` (JSON `{id,version,files,ui_id}`) -> 200.
- `POST /manager/queue/update` (JSON `{id,version,files,ui_id}`) -> 200.
- `POST /manager/queue/disable` (JSON `{id,version,files,ui_id}`) -> 200. Renames
  the pack folder to `.disabled`.
- `GET /manager/queue/update_all?mode=<...>` -> 200 (403 on policy). Saves an
  autosave snapshot then enqueues updates for all installed packs.
- `POST /manager/queue/install_model` (JSON model item `{name,type,base,save_path,
  filename,url,ui_id}`) -> 200 (400 invalid request, 403 policy). The item must
  match a catalog entry by save path, base and filename; the download is then
  enqueued. Filename must not contain path separators; `save_path` may be `default`,
  a model subdirectory, or a `custom_nodes/<repo>/...` path.

### Install helpers (direct)
- `POST /customnode/install/git_url` (raw text body = git url) -> 200/400.
  Clones the repository into the custom nodes path (policy-gated to a restrictive
  level).
- `POST /customnode/install/pip` (raw text body = package list) -> 200. Pip
  installs the given packages (same policy gate).

### ComfyUI update & restart
- `GET /comfyui_manager/comfyui_versions` -> JSON `{versions:[...],current}` (400
  on failure).
- `GET /comfyui_manager/comfyui_switch_version?ver=<tag>` -> 200/400. Switches the
  ComfyUI repo to the given tag.
- `GET /manager/queue/update_comfyui` -> 200. Enqueues a ComfyUI update (stable or
  nightly per `update_policy`).
- `GET /manager/reboot` -> 200 (403 on policy). Re-executes the ComfyUI process.

### Snapshots
- `GET /snapshot/getlist` -> JSON `{items:[...]}` (snapshot names).
- `GET /snapshot/save` -> 200/400. Saves a snapshot with postfix `snapshot`.
- `GET /snapshot/get_current` -> JSON of the current custom node / pip state.
- `GET /snapshot/remove?target=<name>` -> 200/400 (403 on policy).
- `GET /snapshot/restore?target=<name>` -> 200/400 (403 on policy). Copies the
  snapshot into the startup-scripts dir for restoration on next boot.

### Preferences
- `GET /manager/preview_method[?value=<auto|latent2rgb|taesd|none>]` -> text of the
  current method; with `value`, sets it and writes config.
- `GET /manager/db_mode[?value=<local|cache|remote>]` -> text / set.
- `GET /manager/policy/component[?value=<workflow|...>]` -> text / set.
- `GET /manager/policy/update[?value=<stable-comfyui|nightly-comfyui|...>]` ->
  text / set.
- `GET /manager/share_option[?value=<all|...>]` -> text / set (writes config).
- `GET /manager/version` -> plain text manager version (`V3.37`).

### Channel selection
- `GET /manager/channel_url_list[?value=<name-or-url>]` ->
  - Without `value`: JSON `{selected, list:["name::url",...]}` where `selected` is
    the name matching the active channel url (or `custom`).
  - With `value`: looks up the name in the channel registry; a value that is not a
    registered channel name but is itself a valid remote URL is also accepted and
    persisted as the active channel; the active channel URL is then written to the
    settings. Returns 200.

### Announcement
- `GET /manager/notice` -> text/html of the manager news page fetched from
  `https://github.com/ltdrdata/ltdrdata.github.io/wiki/News` (markdown-body div
  extracted, links rewritten to open in a new tab), with a footer line for the
  ComfyUI version and manager version. Falls back to an error text on fetch failure.

### Components
- `POST /manager/component/save` (JSON `{name,workflow}`) -> 200 text = saved file
  path. Named `{name}.json` (or `{packname}.pack` when the workflow has a packname);
  components accumulate by name within the file.
- `POST /manager/component/loads` -> JSON of all saved components ({} when the
  component dir does not exist).

### Third-party auth & sharing
- `GET /manager/get_openart_auth` -> JSON `{openart_key}` (404 when unset).
- `POST /manager/set_openart_auth` (JSON `{openart_key}`) -> 200.
- `GET /manager/get_matrix_auth` -> JSON `{homeserver,username,password}` (404
  when unset).
- `GET /manager/youml/settings` -> JSON settings (404 when unset).
- `POST /manager/youml/settings` (JSON) -> 200.
- `GET /manager/get_comfyworkflows_auth` -> JSON `{comfyworkflows_sharekey}` (404
  when unset).
- `POST /manager/set_esheep_workflow_and_images` (JSON) -> 200. Persists an
  esheep share message.
- `GET /manager/get_esheep_workflow_and_images` -> JSON of the persisted esheep
  share message.
- `POST /manager/share` (JSON `{matrix_auth, cw_auth:{cw_sharekey},
  share_destinations, credits, title, description, is_nsfw, prompt:{workflow,
  output}, potential_outputs, selected_output_index}`) -> JSON
  `{comfyworkflows:{url}, matrix:{success}}` (4xx/5xx on provider failures).
  - Resolves the selected output asset under the output (or temp) directory,
    uploads the image and workflow JSON to comfyworkflows.com via its
    presigned-url API, computes sha256 for referenced model files, and posts the
    artwork to a Matrix room when matrix credentials are provided.

## Seeded data (business fixtures)

- User settings file (per-user `comfy.settings.json`) seeded with
  `Comfy.InstalledVersion`, `Comfy.TutorialCompleted`, and a `Comfy.TestXss`
  setting field.
- User data directory contains a `secret_model.png`, `secret_model.safetensors`
  and `traversal.png` fixture files.
- Manager settings file seeded (see Preferences above); channel list seeded with
  `default`, `recent`, `legacy`, `forked`, `dev`, `tutorial` channels pointing at
  `https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main` (and
  `node_db/...` subpaths).