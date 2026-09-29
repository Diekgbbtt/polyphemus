# JetLinks surface map (reverse-engineered endpoint inventory)

Deployed instance: `jetlinks-community:2.3.0-SNAPSHOT` standalone app, HTTP on `jetlinks:8848`.
Request convention: JSON bodies (`Content-Type: application/json`), the hsweb `ResponseMessage`
wrapper around responses, CORS enabled for all origins. The console UI is a separate Vue app served
by the `ui` container (`http://ui:80`) that proxies `/api` to the backend.

## Authentication and session

The login token issued on authorize is carried on subsequent requests in the `X-Access-Token`
header (the Vue console's `TOKEN_KEY`). hsweb's token parser also accepts Basic authorization
(`Authorization: Basic base64(username:password)`). Endpoints marked "public" do not require the
token; every other route in this document is "authenticated" (requires a valid token) unless a
per-route annotation is noted.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/authorize/login` | - | body `{username, password, verifyKey?, verifyCode?}` -> `{token, userId, permissions, roles, currentAuthority, user}` | public |
| GET | `/authorize/me` | - | -> current `Authentication` (user, permissions, dimensions) | authenticated |
| GET | `/authorize/captcha/config` | - | -> `{enabled, type}` (captcha disabled by config) | public |
| GET | `/user-token/reset` | - | resets the current user's token -> bool | authenticated |
| PUT | `/user-token/check` | - | checks and removes expired tokens -> bool | authenticated |
| GET | `/user-token/token/{token}` | - | -> token info | authenticated |
| GET | `/user-token/user/{userId}` | - | -> all tokens of a user | authenticated |
| GET | `/user-token/user/{userId}/logged` | - | -> bool | authenticated |
| GET | `/user-token/token/{token}/logged` | - | -> bool | authenticated |
| GET | `/user-token/user/total` | - | -> logged-in user count | authenticated |
| GET | `/user-token/token/total` | - | -> token count | authenticated |
| GET | `/user-token` | - | -> all tokens | authenticated |
| DELETE | `/user-token/user/{userId}` | - | kicks a user offline | authenticated |
| DELETE | `/user-token/token/{token}` | - | invalidates a token | authenticated |
| PUT | `/user-token/user/{userId}/{state}` | state in {normal, denied, locked} | updates a user's token state | authenticated |
| PUT | `/user-token/token/{token}/{state}` | state | updates a token's state | authenticated |
| GET | `/user-token/{token}/touch` | - | refreshes a token's validity | authenticated |
| GET | `/user-auth/{userId}` | - | -> a user's `Authentication` | authenticated |

## Standard hsweb CRUD endpoint family

Every controller implementing `ReactiveServiceCrudController` exposes this standard family under its
resource base path (all authenticated, action-gated by the resource):

- `GET /{id:.+}` - get by id
- `POST /_query` - paged dynamic query, body `QueryParamEntity` (`{pageIndex, pageSize, where, orderBy, terms[]}`, `terms[]` entries `{column, termType, value}`)
- `GET /_query` - paged dynamic query via query string
- `POST /_query/no-paging` / `GET /_query/no-paging` - unpaged result stream
- `POST /_count` / `GET /_count` - count
- `POST /_exists` / `GET /_exists` - existence check
- `PATCH` - save (upsert by id), body entity or entity list
- `POST` - insert single, returns the inserted entity
- `POST /_batch` - batch insert, returns count
- `PUT /{id}` - update by id, returns bool
- `DELETE /{id:.+}` - delete by id

CRUD resources present: `/user`, `/user/detail` (query-only), `/role`, `/role/group`,
`/organization`, `/menu`, `/device-instance` (+`/device/instance` alias), `/device-product`
(+`/device/product` alias), `/device/category`, `/protocol`, `/network/config`, `/network/certificate`,
`/gateway/device`, `/notifier/config`, `/notifier/template`, `/alarm/config`, `/alarm/rule/bind`,
`/relation`.

## User, role and organisation administration

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/user/{id}/password/_reset` | id | body: plain-text password string -> bool | authenticated |
| POST | `/user/username/_validate` | - | body: username string -> `ValidationResult` | authenticated |
| POST | `/user/password/_validate` | - | body: password string -> `ValidationResult` | authenticated |
| POST | `/user/me/password/_validate` | - | body: password string -> validates against the current user -> `ValidationResult` | authenticated |
| PUT | `/user/passwd` | - | body `ChangePasswordRequest` -> change own password -> bool | authenticated |
| POST | `/user/detail/_create` | - | body `SaveUserRequest` (user + dimensions) -> user id | authenticated |
| PUT | `/user/detail/{userId}/_update` | userId | body `SaveUserRequest` -> user id | authenticated |
| GET | `/user/detail/{userId}` | userId | -> `UserDetail` | authenticated |
| POST | `/user/detail/_query` | - | body `QueryParamEntity` -> paged `UserDetail` | authenticated |
| GET | `/user/detail` | - | -> current user's `UserDetail` | authenticated |
| PUT | `/user/detail` | - | body `SaveUserDetailRequest` -> save current user's detail | authenticated |
| GET | `/user/detail/types` | - | -> user type list | authenticated |
| POST | `/role/{roleId}/users/_bind` | roleId | body: `[userId]` -> void | authenticated |
| POST | `/role/{roleId}/users/_unbind` | roleId | body: `[userId]` -> void | authenticated |
| POST | `/role/group/detail/_query/tree` | `queryByRole` bool | body `QueryParamEntity` -> role-group + role tree | authenticated |
| GET | `/permission/id/_validate` | `id` | -> `ValidationResult` | authenticated |
| GET | `/menu/_all/tree` (GET/POST) | - | -> full menu tree | authenticated |
| GET | `/menu/user-own/tree` (GET/POST) | - | -> menus the current user can access (tree) | authenticated |
| GET | `/menu/user-own/list` | - | -> menus the current user can access (list) | authenticated |
| POST | `/menu/owner` | - | body: `[owner]` to exclude -> distinct menu owners | public |
| POST | `/menu/owner/tree/{owner}` | owner | body `QueryParamEntity` -> menu tree of an owner | public |
| PUT | `/menu/{targetType}/{targetId}/_grant` | targetType, targetId | body `MenuGrantRequest` -> void | authenticated |
| PUT | `/menu/{targetType}/{targetId}/{owner}/clear-grant` | - | clears menu grant of an owner | authenticated |
| PUT | `/menu/_batch/_grant` | - | body: `[MenuGrantRequest]` -> void | authenticated |
| GET | `/menu/{targetType}/{targetId}/_grant/tree` / `_grant/list` | - | -> grant info as tree/list | authenticated |
| POST | `/menu/permissions` | - | body: `[MenuView]` -> permission list from menus | authenticated |
| POST | `/menu/asset-types` | - | body: `[MenuView]` -> empty (community no data permission) | authenticated |
| PATCH | `/menu/{owner}/_all` | owner | body: `[MenuEntity]` -> replaces an owner's menus | authenticated |
| GET | `/menu/code/_validate` | `code`, `owner`, `appId?` | -> `ValidationResult` | authenticated |
| GET | `/organization/_all/tree` (GET/POST) | - | -> full organisation tree | authenticated |
| GET | `/organization/_all` (GET/POST) | - | -> all organisations | authenticated |
| GET | `/organization/_query/_children/tree` / `/_query/_children` | - | -> query with children | authenticated |
| POST | `/organization/{id}/users/_bind` / `/users/_unbind` | id | body: `[userId]` -> count | authenticated |
| POST | `/autz-setting/detail/_save` | - | body: `[AuthorizationSettingDetail]` -> bool | authenticated |
| GET | `/autz-setting/detail/{targetType}/{target}` | - | -> permission detail | authenticated |
| PATCH | `/user/third-party/{type}/{provider}` | type, provider | body: `[ThirdPartyBindUserInfo]` (deprecated bind) | authenticated |
| POST | `/user/third-party/{type}/{provider}/_bind` | - | body: `[ThirdPartyBindUserInfo]` -> void | authenticated |
| POST | `/user/third-party/me/{type}/{provider}/{bindCode}/_bind` | - | binds the current user by bind code | authenticated |
| POST | `/user/third-party/{id}/_unbind` | id | -> void | authenticated |
| GET | `/user/third-party/{type}/{provider}` | - | -> bindings for type/provider | authenticated |
| GET | `/user/third-party/me` | - | -> current user's bindings | authenticated |
| DELETE | `/user/third-party/me/{bindingId}` | bindingId | unbinds the current user | authenticated |
| GET | `/user/settings/{type}` | type | -> current user's settings of a type | authenticated |
| GET | `/user/settings/{type}/{key}` | - | -> a single setting | authenticated |
| POST | `/user/settings/{type}` | type | body `UserSettingEntity` -> create setting | authenticated |
| PATCH | `/user/settings/{type}/{key}` | - | body `UserSettingEntity` -> save setting | authenticated |
| DELETE | `/user/settings/{type}/{key}` | - | -> delete setting | authenticated |

## Protocol management

Base `/protocol`, resource `protocol-supports`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/protocol/{id}/_deploy` | id | deploys a protocol -> bool (deprecated) | authenticated |
| POST | `/protocol/{id}/_un-deploy` | id | undeploys a protocol -> bool (deprecated) | authenticated |
| GET | `/protocol/{id:.+}/exists` | id | -> bool | authenticated |
| GET | `/protocol/providers` | - | -> protocol loader provider ids (e.g. `jar`) | authenticated |
| GET | `/protocol/supports` | query | -> `[ProtocolInfo {id, name, configuration, description}]` | authenticated |
| GET | `/protocol/supports/{transport}` | transport | -> protocols supporting a transport | authenticated |
| GET | `/protocol/{id}/{transport}/configuration` | id, transport | -> transport configuration `ConfigMetadata` | authenticated |
| GET | `/protocol/{id}/{transport}/metadata` | - | -> default model metadata string | authenticated |
| GET | `/protocol/{id}/transports` | id | -> `[TransportDetail]` | authenticated |
| GET | `/protocol/{id}/transport/{transport}` | - | -> `TransportDetail` | authenticated |
| POST | `/protocol/{id}/detail` | id | -> `ProtocolDetail` | authenticated |
| POST | `/protocol/convert` | `transport?` | body: `ProtocolSupportEntity`; loads the definition and returns `ProtocolDetail` (hidden in docs) | authenticated |
| POST | `/protocol/decode` | - | body `ProtocolDecodeRequest` {entity, request}; decodes payload through the protocol -> JSON string (hidden) | authenticated |
| POST | `/protocol/encode` | - | body `ProtocolEncodeRequest`; encodes payload -> JSON string (hidden) | authenticated |
| GET | `/protocol/units` | - | -> value unit list | authenticated |
| POST | `/protocol/default-protocol/_save` | - | saves the built-in default protocol from a packaged jar -> void | authenticated |

`ProtocolSupportEntity` fields: `id, name, description, type, state (1 enabled, 0 disabled),
configuration {location, provider, fileId, ...}, creatorId, createTime, creatorName, modifierId,
modifyTime, modifierName`. Stored in table `dev_protocol`. A `jar`-type protocol resolves its jar
from `configuration.location` when it starts with `http` (downloaded, cached by `id_md5(location)`),
or from `configuration.fileId` via the file manager; `configuration.provider` names the class to
load.

## Device product and category

Base `/device-product` (`/device/product` alias), resource `device-product`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/device-product/{id:.+}/config-metadata` | id | -> product config `ConfigMetadata` list | authenticated |
| GET | `/device-product/{id:.+}/{accessId:.+}/config-metadata` | id, accessId | -> config metadata for an access way | authenticated |
| GET | `/device-product/{id:.+}/config-metadata/{metadataType}/{metadataId}/{typeId}` | - | -> expanded model config definitions | authenticated |
| GET | `/device-product/metadata/codecs` | - | -> supported model formats | authenticated |
| POST | `/device-product/metadata/convert-to/{id}` | id | body: model JSON -> converted model JSON | authenticated |
| POST | `/device-product/metadata/convert-from/{id}` | id | body: model JSON -> platform model JSON | authenticated |
| GET | `/device-product/{id:.+}/exists` | id | -> bool | authenticated |
| GET | `/device-product/id/_validate` | `id` | -> `ValidationResult` | authenticated |
| POST | `/device-product/detail/_query` / `detail/_query/no-paging` | - | body `QueryParamEntity` -> product detail pages/list | authenticated |
| POST | `/device-product/{productId:.+}/deploy` / `/undeploy` | productId | activates / deactivates a product -> count | authenticated |
| GET | `/device-product/storage/policies` | - | -> data storage policy list | authenticated |
| POST | `/device-product/{productId:.+}/agg/_query` | productId | body `AggRequest` {query, columns} -> aggregated property rows | authenticated |
| POST | `/device-product/{productId}/properties/_query` | - | body `QueryParamEntity` -> columnar property pages (columnar storage only) | authenticated |
| POST | `/device-product/{productId}/metadata/merge-to-device` | - | merges product model onto all its devices | authenticated |
| GET | `/device-product/{productId}/property-metadata/template.{format}` | format in {csv, xlsx} | -> property-model excel template download | authenticated |
| POST | `/device-product/{productId}/property-metadata/import` | `fileUrl` | -> parsed property-model JSON | authenticated |

Base `/device/category`, resource `device-category`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/device/category` | query | -> all categories | authenticated |
| GET | `/device/category/_tree` (GET/POST) | query / body | -> category tree | authenticated |

## Device instance

Base `/device-instance` (`/device/instance` alias), resource `device-instance`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/device-instance/{id:.+}/detail` | id | -> `DeviceDetail` | authenticated |
| POST | `/device-instance/{deviceId:.+}/properties/_read` | deviceId | body: `[propertyId]` -> read instruction result | authenticated |
| GET | `/device-instance/{id:.+}/config-metadata` | id | -> device config definitions | authenticated |
| GET | `/device-instance/{id:.+}/config-metadata/{metadataType}/{metadataId}/{typeId}` | - | -> expanded config definitions | authenticated |
| GET | `/device-instance/bind-providers` | - | -> device bind providers | authenticated |
| GET | `/device-instance/{id:.+}/state` | id | -> device online state | authenticated |
| POST | `/device-instance/{deviceId:.+}/deploy` | deviceId | activates a device -> `DeviceDeployResult` | authenticated |
| PUT | `/device-instance/{deviceId:.+}/configuration/_reset` | - | resets device configuration -> `{...}` | authenticated |
| GET | `/device-instance/deploy` | query | batch activate (SSE stream) | authenticated |
| POST | `/device-instance/{deviceId:.+}/undeploy` | - | deactivates a device -> count | authenticated |
| POST | `/device-instance/{deviceId:.+}/disconnect` | - | disconnects a device -> bool | authenticated |
| GET | `/device-instance/state/_sync` | query | syncs device states (SSE) | authenticated |
| GET | `/device-instance/{deviceId:.+}/properties/latest` | deviceId | -> latest properties | authenticated |
| GET | `/device-instance/{deviceId:.+}/properties` | - | -> properties by condition | authenticated |
| GET | `/device-instance/{deviceId:.+}/property/{property:.+}` | - | -> latest value of a property | authenticated |
| GET | `/device-instance/{deviceId:.+}/property/{property}/_query` (GET/POST) | - | -> paged property history | authenticated |
| POST | `/device-instance/{deviceId:.+}/property/{property}/_query/no-paging` | - | -> unpaged property history | authenticated |
| GET | `/device-instance/{deviceId:.+}/properties/_query` | - | -> paged properties (deprecated) | authenticated |
| GET | `/device-instance/{deviceId:.+}/event/{eventId}` (GET/POST) | `format` bool | -> paged event records | authenticated |
| GET | `/device-instance/{deviceId:.+}/logs` (GET/POST) | - | -> paged device operation logs | authenticated |
| DELETE | `/device-instance/{deviceId}/tag/{tagId:.+}` | - | deletes a device tag | authenticated |
| PUT | `/device-instance/batch/_delete` | - | body: `[deviceId]` (unactivated only) -> count | authenticated |
| PUT | `/device-instance/batch/_unDeploy` | - | body: `[deviceId]` -> batch deactivate | authenticated |
| PUT | `/device-instance/batch/_deploy` | - | body: `[deviceId]` -> batch activate | authenticated |
| GET | `/device-instance/{deviceId}/tags` | deviceId | -> device tags | authenticated |
| GET | `/device-instance/tags/key` | - | -> distinct tag keys | authenticated |
| PATCH | `/device-instance/{deviceId}/tag` | deviceId | body: `[DeviceTagEntity]` -> saved tags | authenticated |
| GET | `/device-instance/{productId}/import` | `autoDeploy`, `fileUrl`, `fileId`, `speed` | excel import of device rows (SSE) | authenticated |
| GET | `/device-instance/{productId}/import/_withlog` | `autoDeploy`, `fileUrl`, `speed` | excel import with log download (SSE) | authenticated |
| GET | `/device-instance/{productId}/template.{format}` | format | -> device import template download | authenticated |
| GET | `/device-instance/{productId}/export.{format}` | format | -> device rows export per product | authenticated |
| GET | `/device-instance/export.{format}` | format | -> device rows export (no tags/config) | authenticated |
| PUT | `/device-instance/{deviceId:.+}/shadow` | deviceId | body: JSON string -> set device shadow | authenticated |
| GET | `/device-instance/{deviceId:.+}/shadow` | - | -> device shadow JSON | authenticated |
| PUT | `/device-instance/{deviceId:.+}/property` | deviceId | body `{property: value}` -> write instruction result | authenticated |
| POST | `/device-instance/{deviceId:.+}/function/{functionId}` | - | body `{param: value}` -> invoke function result | authenticated |
| POST | `/device-instance/{deviceId:.+}/agg/_query` | - | body `AggRequest` -> aggregated property rows | authenticated |
| POST | `/device-instance/{deviceId:.+}/properties/_query/no-paging` | - | body `QueryParamEntity` -> columnar properties | authenticated |
| POST | `/device-instance/{deviceId:.+}/message` | deviceId | body: device message map -> send instruction result | authenticated |
| POST | `/device-instance/messages` | `where` | body: `[message map]` -> batch send | authenticated |
| PUT | `/device-instance/{id}/metadata` | id | body: model JSON -> update derived model | authenticated |
| DELETE | `/device-instance/{id}/metadata` | id | resets derived model | authenticated |
| PUT | `/device-instance/{id}/metadata/merge-product` | id | merges the product model in | authenticated |
| GET | `/device-instance/{id:.+}/exists` | id | -> bool | authenticated |
| GET | `/device-instance/id/_validate` | `id` | -> `ValidationResult` | authenticated |
| POST | `/device-instance/{productId}/property-metadata/import` | `fileUrl` | -> parsed property-model JSON | authenticated |
| GET | `/device-instance/{deviceId}/property-metadata/template.{format}` | format | -> property-model template download | authenticated |
| PATCH | `/device-instance/{deviceId}/relations` | deviceId | body: `[SaveRelationRequest]` -> save relations | authenticated |
| GET | `/device-instance/{deviceId}/metric/property/{property}` (GET/PATCH) | - | -> reads/saves a property metric config | authenticated |

Legacy `/device` command surface (deprecated, resource `device-instance`):
`GET /device/{deviceId}/property/{property:.+}`, `GET /device/standard/{deviceId}/property/{property:.+}`,
`POST /device/setting/{deviceId}/property`, `POST /device/invoked/{deviceId}/function/{functionId}`,
`POST /device/{deviceId}/properties`.

## Gateway devices, mappings, codecs

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/device/gateway/_query` | query | -> paged gateway devices with children | authenticated |
| GET | `/device/gateway/{id}` | id | -> gateway detail with children | authenticated |
| POST | `/device/gateway/{gatewayId}/bind/{deviceId}` | - | binds one child device | authenticated |
| POST | `/device/gateway/{gatewayId}/bind` | - | body: `[deviceId]` -> binds many children | authenticated |
| POST | `/device/gateway/{gatewayId}/unbind/{deviceId}` | - | unbinds one child | authenticated |
| POST | `/device/gateway/{gatewayId}/unbind` | - | body: `[deviceId]` -> unbinds many children | authenticated |
| PATCH | `/device/metadata/mapping/device/{deviceId}` | - | body: `[DeviceMetadataMappingEntity]` -> save device mapping | authenticated |
| PATCH | `/device/metadata/mapping/product/{productId}` | - | body: `[DeviceMetadataMappingEntity]` -> save product mapping | authenticated |
| GET | `/device/metadata/mapping/product/{productId}` / `/device/{deviceId}` | - | -> mapping details | authenticated |
| POST | `/device/transparent-codec/decode-test` | - | body `TransparentMessageDecodeRequest` -> decode response | authenticated |
| GET | `/device/transparent-codec/{productId}/{deviceId}.d.ts` / `/{productId}.d.ts` | - | -> model TypeScript declares | authenticated |
| GET | `/device/transparent-codec/{productId}/{deviceId}` / `/{productId}` | - | -> codec rule | authenticated |
| POST | `/device/transparent-codec/{productId}/{deviceId}` / `/{productId}` | - | body `TransparentMessageCodecRequest` -> save codec rule | authenticated |
| DELETE | `/device/transparent-codec/{productId}/{deviceId}` / `/{productId}` | - | resets codec rule | authenticated |

## Network and gateway access

Base `/network/config`, resource `network-config`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/network/config/{networkType}/_detail` | networkType | -> `[ChannelInfo]` of a type | authenticated |
| GET | `/network/config/{networkType}/_alive` | `include` | -> alive/usable components of a type | authenticated |
| GET | `/network/config/supports` | - | -> supported component types | authenticated |
| POST | `/network/config/{id}/_start` / `/{id}/_shutdown` | id | starts/stops a component | authenticated |

Base `/gateway/device`, resource `device-gateway`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/gateway/device/{id}/_startup` / `/{id}/_pause` / `/{id}/_shutdown` | id | starts, pauses, stops a device gateway | authenticated |
| GET | `/gateway/device/{id}/detail` | id | -> gateway detail | authenticated |
| POST | `/gateway/device/detail/_query` | - | body `QueryParamEntity` -> paged gateway details | authenticated |
| GET | `/gateway/device/providers` | - | -> access way providers | authenticated |
| GET | `/gateway/device/sessions` | `pageIndex`, `pageSize` | -> device sessions | authenticated |
| GET | `/gateway/device/sessions/{serverId}` | - | -> sessions of a server node | authenticated |
| DELETE | `/gateway/device/session/{deviceId}` | deviceId | removes a device session | authenticated |

Base `/network/certificate`, resource `certificate`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/network/certificate/{id}/detail` | id | -> certificate string | authenticated |
| POST | `/network/certificate/upload` | multipart `file` | -> certificate BASE64 | authenticated |

Base `/network/resources`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/network/resources/alive` | - | -> alive bound-all resources | authenticated |
| GET | `/network/resources/alive/_all` | - | -> all cluster node resources | authenticated |
| GET | `/network/resources/alive/_current` | - | -> current node resources | authenticated |

## Scene automation and alarms

Base `/scene`, resource `rule-scene` (both SceneController and SceneUtilsController).

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/scene` | - | body `SceneRule` -> created scene | authenticated |
| PUT | `/scene/{id}` | id | body `SceneRule` -> update scene | authenticated |
| PUT | `/scene/{id}/_disable` / `/{id}/_enable` | id | disables/enables a scene | authenticated |
| POST | `/scene/{id}/_execute` | id | body: context map -> execute scene manually | authenticated |
| POST | `/scene/batch/_execute` | - | body: `[SceneExecuteRequest]` -> batch execute | authenticated |
| DELETE | `/scene/{id}` | id | deletes a scene | authenticated |
| GET | `/scene/trigger/supports` | - | -> trigger definitions | authenticated |
| GET | `/scene/action/supports` | - | -> action definitions | authenticated |
| GET | `/scene/aggregation/supports` | - | -> aggregation definitions | authenticated |
| POST | `/scene/parse-term-column` | - | body `SceneRule` -> condition columns | authenticated |
| POST | `/scene/parse-array-child-term-column` | - | body metadata -> array child columns | authenticated |
| POST | `/scene/parse-variables` | `branch`, `branchGroup`, `action` | body `SceneRule` -> output variables | authenticated |
| GET | `/scene/device-selectors` | - | -> device selectors | authenticated |

Base `/alarm/config`, resource `alarm-config`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/alarm/config/{id}/_enable` / `/{id}/_disable` | id | enables/disables an alarm config | authenticated |
| GET | `/alarm/config/target-type/supports` | - | -> alarm target types | authenticated |
| PATCH | `/alarm/config/default/level` | - | body: `[AlarmLevelInfo]` -> save default levels | authenticated |
| PATCH | `/alarm/config/level` | - | body `AlarmLevelEntity` -> save a level | authenticated |
| POST | `/alarm/config/detail/_query` | - | body `QueryParamEntity` -> paged alarm config details | authenticated |
| GET | `/alarm/config/default/level` | - | -> default alarm level | authenticated |

Base `/alarm/record`, resource `alarm-record`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/alarm/record/{dimensionType}/_query` | dimensionType | body `QueryParamEntity` -> paged records | authenticated |
| POST | `/alarm/record/_handle` | - | body `AlarmHandleInfo` -> handle an alarm | authenticated |
| POST | `/alarm/record/handle-history/_query` | - | body `QueryParamEntity` -> handle history (deprecated) | authenticated |
| POST | `/alarm/record/{id}/handle-history/_query` | id | -> handle history of a record | authenticated |
| POST | `/alarm/record/{dimensionType}/_handle` | dimensionType | body `AlarmHandleInfo` (deprecated) | authenticated |
| POST | `/alarm/record/handle-history/{dimensionType}/{recordId}/_query` | - | -> handle history by dimension | authenticated |

Base `/alarm/history`, resource `alarm-record`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/alarm/history/_query` | - | body `QueryParamEntity` (deprecated) | authenticated |
| POST | `/alarm/history/{alarmConfigId}/_query` | alarmConfigId | -> alarm history of a config | authenticated |
| POST | `/alarm/history/alarm-record/{recordId}/_query` | recordId | -> history of a record | authenticated |
| POST | `/alarm/history/{dimensionType}/{alarmConfigId}/_query` | - | -> history by dimension and config | authenticated |

Base `/alarm/rule/bind`, resource `alarm-config`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/alarm/rule/bind/{alarmId}/_delete` | alarmId | body: `[ruleId]` -> delete bindings | authenticated |
| POST | `/alarm/rule/bind/{alarmId}/{ruleId}/_delete` | - | body: `[branchIndex]` -> delete branch bindings | authenticated |
| POST | `/alarm/rule/bind/_delete` | - | body: `[AlarmRuleBindEntity]` -> bulk delete | authenticated |

## Notifications

Base `/notifier`, resource `notifier`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/notifier/{notifierId}/_send` | notifierId | body `{template: NotifyTemplateEntity, context: {}}` -> void | authenticated |
| POST | `/notifier/{notifierId}/{templateId}/_send` | - | body: context map -> void | authenticated |

Base `/notifier/config`, resource `notifier`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/notifier/config/{type}/{provider}/metadata` | - | -> config `ConfigMetadata` | authenticated |
| GET | `/notifier/config/types` | - | -> notify types with provider info | authenticated |
| GET | `/notifier/config/type/{type}/providers` | type | -> providers of a type | authenticated |

Base `/notifier/template`, resource `template`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/notifier/template/{configId}/_query` | configId | body `QueryParamEntity` -> templates for a config | authenticated |
| POST | `/notifier/template/{configId}/detail/_query` | - | -> template details with variable definitions | authenticated |
| GET | `/notifier/template/{templateId}/detail` | templateId | -> template detail | authenticated |
| GET | `/notifier/template/{type}/{provider}/config/metadata` | - | -> template config metadata | authenticated |

Base `/notify/channel`, resource `notify-channel`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/notify/channel/providers` | - | -> channel provider list | authenticated |
| PATCH | `/notify/channel` | - | body: `[SubscriberProviderInfo]` -> save channels | authenticated |
| PATCH | `/notify/channel/{providerId}` | providerId | body: `[NotifySubscriberChannelEntity]` -> save one provider's channels | authenticated |
| DELETE | `/notify/channel/{channelId}` | channelId | deletes a channel | authenticated |
| POST | `/notify/channel/{providerId}/enable` / `/{providerId}/disable` | providerId | enables/disables a provider subscription | authenticated |
| PUT | `/notify/channel/{providerId}` | providerId | body `NotifySubscriberProviderEntity` -> update provider | authenticated |
| GET | `/notify/channel/all-for-save` | - | -> all channel configs | authenticated |
| GET | `/notify/channel/all` | - | -> channels the current user can access | authenticated |
| GET | `/notify/channel/{providerId}/variables` | providerId | -> built-in variables | authenticated |

Base `/notifications` (inbox and subscriptions).

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/notifications/subscriptions/_query` (GET/POST) | - | -> current user's subscriptions | authenticated |
| PUT | `/notifications/subscription/{id}/_{state}` | state | toggles a subscription state | authenticated |
| DELETE | `/notifications/subscription/{id}` | id | deletes a subscription | authenticated |
| PATCH | `/notifications/subscribe` | - | body: `[NotifySubscriberEntity]` -> subscribe | authenticated |
| GET | `/notifications/providers` | - | -> subscriber providers (deprecated) | authenticated |
| GET | `/notifications/current/providers` | - | -> providers available to the current user | authenticated |
| GET | `/notifications/current/{type}/providers` | type | -> providers of a type for the current user | authenticated |
| GET | `/notifications/_query` (GET/POST) | - | -> the current user's notification records | authenticated |
| GET | `/notifications/{id}/read` | id | -> a notification, marked read | authenticated |
| POST | `/notifications/_{state}` | state in {read, unread} | body: `[id]` -> set notification state | authenticated |
| POST | `/notifications/_{state}/provider` | state | body: `[providerId]` -> set state by provider | authenticated |

Base `/notify/history`, resource `notifier`.

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| POST | `/notify/history/config/{configId}/_query` | configId | body `QueryParamEntity` -> delivery history of a config | authenticated |
| POST | `/notify/history/template/{templateId}/_query` | templateId | -> delivery history of a template | authenticated |

Provider-specific notifier surfaces (all authenticated):

| Method | Path | Params | Request / Response |
| --- | --- | --- | --- |
| GET | `/notifier/dingtalk/corp/{configId}/departments` | `fetchChild` bool | -> DingTalk departments |
| GET | `/notifier/dingtalk/corp/{configId}/departments/tree` | - | -> department tree |
| GET | `/notifier/dingtalk/corp/{configId}/{departmentId}/users` | - | -> department users |
| GET | `/notifier/dingtalk/corp/{configId}/users` | - | -> all users |
| GET | `/notifier/dingtalk/corp/{configId}/oauth2/binding-user-url` | `authCode` | -> OAuth2 authorize url |
| GET | `/notifier/dingtalk/corp/oauth2/user-bind-code` | `authCode`, `configId` | -> user bind code |
| GET | `/notifier/sms/aliyun/{configId}/signs` | configId | -> SMS signs |
| GET | `/notifier/sms/aliyun/{configId}/templates` | configId | -> SMS templates |
| GET | `/notifier/wechat/corp/{configId}/tags` | configId | -> WeChat tags |
| GET | `/notifier/wechat/corp/{configId}/departments` | - | -> departments |
| GET | `/notifier/wechat/corp/{configId}/{departmentId}/users` | - | -> department users |
| GET | `/notifier/wechat/corp/{configId}/users` | - | -> all users |
| GET | `/notifier/wechat/corp/{configId}/{templateId}/oauth2/binding-user-url` | `authCode` | -> OAuth2 url |
| GET | `/notifier/wechat/corp/oauth2/user-bind-code` | `authCode`, `configId` | -> user bind code |

## Dashboard, logs, system configuration, files, relations, platform info

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/dashboard/defs` | - | -> dashboard definitions | authenticated |
| GET | `/dashboard/def/{dashboard}/{object}/measurements` | - | -> measurement definitions | authenticated |
| GET | `/dashboard/{dashboard}/{object}/{measurement}/{dimension}` | query params | real-time measurement value stream (SSE) | authenticated |
| POST | `/dashboard/_multi` | - | body: `[DashboardMeasurementRequest]` -> batch values | authenticated |
| GET | `/dashboard/_multi` | `requestJson` | batch values (SSE) | authenticated |
| GET | `/logger/access/_query` (GET/POST) | - | body `QueryParamEntity` -> paged access logs | authenticated |
| GET | `/logger/system/_query` (GET/POST) | - | body `QueryParamEntity` -> paged system logs | authenticated |
| GET | `/system/config/scopes` | - | -> config scopes | authenticated |
| GET | `/system/config/{scope}` | scope | -> scope config values (public-access scopes or logged-in) | public for public scopes |
| GET | `/system/config/{scope}/_detail` | scope | -> scope config property values | authenticated |
| POST | `/system/config/scopes` | - | body: `[scope]` -> scope configs | authenticated |
| POST | `/system/config/{scope}` | scope | body: value map -> save config | authenticated |
| POST | `/system/config/scope/_save` | - | body: `[{scope, properties}]` -> bulk save | authenticated |
| GET | `/system/resources/{type}` | type | -> resource strings (admin username only) | authenticated |
| GET | `/system/resources/{id}.d.ts` | id | -> TypeScript declaration resource | authenticated |
| GET | `/command-supports/services` | - | -> command services | authenticated |
| GET | `/command-supports/service/{serviceId}/commands` | - | -> command metadata | authenticated |
| GET | `/command-supports/service/{serviceId}/exists` | - | -> bool | authenticated |
| GET | `/relation/{type}/{id}/related` | - | -> related objects | authenticated |
| PATCH | `/relation/{type}/{id}/_bind` | - | body: `[SaveRelationRequest]` -> save relations | authenticated |
| GET | `/relation/types` | - | -> relation object types | authenticated |
| GET | `/relation/{type}/relations` | type | -> relations of a type | authenticated |
| GET | `/relation/_validate` | `objectType`, `relation`, `targetType` | -> `ValidationResult` | authenticated |
| POST | `/file/upload` | multipart `file` | -> `FileInfo {id, name, length, md5, sha256, accessUrl, ...}` | authenticated |
| GET | `/file/{fileId}` | `accessKey?` | streams the file; non-public files need `accessKey` or a logged-in user | public (subject to file access rule) |
| DELETE | `/file/{fileId}` | fileId | deletes a file | authenticated |
| GET | `/cluster/nodes` | - | -> cluster server nodes | authenticated |
| GET | `/system/version` | - | -> platform version | public |
| GET | `/system/apis` | - | -> API base path and url info | public |

## Maintenance diagnostics console (added to the deployed image)

Base `/system/maintenance`. Annotated `@Authorize(ignore = true)` - public. Renders an HTML console
at the base path and exposes three operations:

| Method | Path | Params | Request / Response | Auth |
| --- | --- | --- | --- | --- |
| GET | `/system/maintenance` and `/system/maintenance/` | - | -> HTML diagnostics console page | public |
| GET | `/system/maintenance/logs/export` | `path` | reads the file at `path` and returns its bytes as text/plain; on failure returns 404 with the error message | public |
| POST | `/system/maintenance/notify/webhook/preview` | - | body `{"url": "..."}` -> `{url, status, body}` (up to 8192 bytes of body); follows redirects, 3s timeouts | public |
| POST | `/system/maintenance/gateway/diagnostics/ping` | - | body `{"target": "..."}` -> `{target, command, exitCode, stdout, stderr}` (up to 8192 bytes each); runs `ping -c 1 <target>` via a shell with a 5s wait | public |

## OpenAPI documentation

- `http://jetlinks:8848/doc.html` - knife4j aggregate doc page (the advertised API docs entry point)
- `http://jetlinks:8848/swagger-ui.html` - springdoc swagger ui
- OpenAPI groups per the config: device management, rule engine, notify management, device access
  (network/gateway/protocol), system management.

## Response envelope and global behaviour

- All responses are wrapped by the hsweb response wrapper as `ResponseMessage` (excluded for
  `org.springdoc`).
- CORS is enabled for all origins and the `GET, POST, PUT, PATCH, DELETE, OPTIONS` methods.
- Every handled request is recorded by the access-logger (ip, url, describe, action) and queryable
  through the access-log surface.
- File access URLs are built from the configured static location
  (`http://jetlinks:8848/upload`); stored files live under the file-manager storage base path.