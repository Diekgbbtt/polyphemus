# JetLinks Community (2.3.0-SNAPSHOT)

## Overview

JetLinks Community is a reactive, WebFlux-based enterprise IoT platform (Spring Boot 2.x, Java 8)
that registers IoT device products and device instances, connects devices over multiple network
protocols through configurable device gateways and network components, ingests device
properties/events/messages into time-series storage, and drives scene automation and alarms through
a rule engine. It is delivered as a single standalone application on port 8848 exposing a JSON API
plus an OpenAPI doc page, with a separate Vue UI container, and is backed by PostgreSQL, Redis and
Elasticsearch. The deployed instance is the official image with an added unauthenticated
maintenance-diagnostics console for device operation log export, notification webhook preview and
gateway ping diagnostics.

## Services

### login-and-authorize
- contract: Signs an operator in with a username and password, returning an authentication result that carries the user, granted permissions and role dimensions; also reports the current user's permission information.
- exposure: public (login), authenticated (current user)

### user-token-session
- contract: Issues, resolves, resets and invalidates the access tokens that keep an operator's login alive, and exposes the token management and token-state endpoints for users and tokens.
- exposure: authenticated

### login-captcha
- contract: Reports whether captcha verification is enabled for login and carries the captcha code verification during authorization when enabled.
- exposure: public

### current-user-profile
- contract: Reads and saves the currently signed-in user's own profile detail and personal settings keyed by setting type and key.
- exposure: authenticated

### user-administration
- contract: Creates, updates, queries and deletes platform users, changes a user's enabled state, resets a user's password, and validates username and password against the platform's rules; also exposes the user detail, user types and current-user password checks.
- exposure: authenticated

### role-management
- contract: Maintains the platform roles and binds or unbinds users to a role.
- exposure: authenticated

### role-group-management
- contract: Maintains role groups and queries the group-and-role tree used to organise roles.
- exposure: authenticated

### permission-catalog
- contract: Maintains the permission catalog and validates that a permission id is well-formed and not already in use.
- exposure: authenticated

### menu-management
- contract: Maintains the application menus as a tree, reads the menus a user can access, grants or clears menu grants for a target type and target, and validates menu codes.
- exposure: authenticated (menu owner listing and tree for a given owner are public)

### organization-management
- contract: Maintains the organisation tree and binds or unbinds users to an organisation.
- exposure: authenticated

### authorization-assignment
- contract: Reads and saves the full permission-assignment detail (permissions and menus) applied to a target type and target id.
- exposure: authenticated

### third-party-user-binding
- contract: Binds, lists and unbinds third-party identity bindings (provider, type, bind code) to platform users, including binding the current user by a bind code.
- exposure: authenticated

### device-product-management
- contract: Maintains device products (a product is the model definition for a family of devices), activates and deactivates them, reads the configuration metadata a product or an access way requires, lists the supported data storage policies, queries product details, aggregates product device properties, merges product metadata down to devices and imports product property metadata from excel.
- exposure: authenticated

### device-category
- contract: Maintains the product categories and reads them as a flat list or tree.
- exposure: authenticated

### device-instance-management
- contract: Maintains device instances (a device belongs to a product and can be a gateway or child), reads device detail and online state, activates, deactivates and disconnects devices, batches those lifecycle operations, resets a device's configuration, manages device tags, imports and exports device rows as excel, and reads or updates a device's derived metadata.
- exposure: authenticated

### device-data-query
- contract: Reads a device's latest or historical property values, event records and operation logs, queries property history, aggregates device properties, reads property metrics, and queries a device's latest data across properties.
- exposure: authenticated

### device-command-and-control
- contract: Sends property-read and property-write instructions to a device, invokes device functions, sends arbitrary device messages and batch messages, and reads or writes the device shadow.
- exposure: authenticated

### gateway-device-management
- contract: Queries gateway devices with their children and binds or unbinds child devices to a gateway device, guarding against cyclic parent-child dependencies.
- exposure: authenticated

### device-metadata-mapping
- contract: Maintains the metadata mapping rules used to translate a device's model onto a product or device scope.
- exposure: authenticated

### transparent-message-codec
- contract: Maintains transparent (raw payload) message decode rules per product and per device, tests a decode configuration, and serves TypeScript declarations of product and device models.
- exposure: authenticated

### device-gateway-access
- contract: Maintains the device gateways that bridge network components into the platform, starts, pauses and stops them, lists the supported access ways, and inspects and removes live device sessions.
- exposure: authenticated

### network-component-management
- contract: Maintains the network components (the concrete TCP, MQTT, HTTP server and other connections by type), starts and stops them, and lists the component types and the components that are alive or usable per type.
- exposure: authenticated

### network-certificate-management
- contract: Maintains TLS certificates used by network components and uploads certificate files returned as BASE64.
- exposure: authenticated

### network-resource-monitoring
- contract: Reports the currently alive network resource hosts and ports on the cluster nodes.
- exposure: authenticated

### protocol-management
- contract: Maintains the message protocol definitions (name, type, state and configuration), publishes and unpublishes them, lists the supported protocol providers and the registered protocols with their transports, reads transport configuration metadata and default model metadata, lists value units, and can save the built-in default protocol.
- exposure: authenticated

### protocol-codec-debug
- contract: Converts a protocol definition into its detail, and decodes or encodes a device payload through a given protocol definition for debugging purposes.
- exposure: authenticated

### scene-automation
- contract: Maintains the automation scenes (a scene is a trigger-condition-action rule), enables and disables them, and executes a scene or a batch of scenes manually with a context.
- exposure: authenticated

### scene-modeling
- contract: Lists the supported scene trigger, action and aggregation definitions, parses the condition columns and output variables a scene rule exposes, and lists the device selectors usable in a scene.
- exposure: authenticated

### alarm-configuration
- contract: Maintains the alarm configurations, enables and disables them, lists the supported alarm target types, saves and reads the default and per-config alarm levels, and queries alarm configuration detail.
- exposure: authenticated

### alarm-records
- contract: Queries alarm records by dimension, marks an alarm as handled with a handle type and description, and queries the alarm handling history per record or dimension.
- exposure: authenticated

### alarm-history
- contract: Queries the alarm history of a configuration, a record or a dimension.
- exposure: authenticated

### alarm-rule-binding
- contract: Binds alarm configurations to scene rules and deletes those bindings per alarm, per rule branch or in bulk.
- exposure: authenticated

### notifier-configuration
- contract: Maintains the notification configurations (each notifier config pairs a notify type with a provider), lists the supported notify types and providers, and reads the configuration metadata a type and provider require.
- exposure: authenticated

### notifier-template
- contract: Maintains the notification templates, reads a template's detail and variable definitions, lists templates for a configuration, and reads the template configuration metadata for a type and provider.
- exposure: authenticated

### notifier-sending
- contract: Sends a notification through a notifier configuration, either with an inline template or with a saved template, over a context of variables.
- exposure: authenticated

### notification-subscription
- contract: Manages a signed-in user's notification inbox: reads and marks their notifications as read or unread, and subscribes, unsubscribes and toggles their notification subscriptions per provider.
- exposure: authenticated

### notify-channel-configuration
- contract: Maintains the notification channels (the per-provider delivery channels and their grants) and the provider enablement, lists the channel providers and the channels a user may access, and reads a provider's built-in variables.
- exposure: authenticated

### notify-history
- contract: Queries the notification delivery history by configuration id or template id.
- exposure: authenticated

### dingtalk-notifier
- contract: Lists the DingTalk corporate departments and users reachable through a DingTalk configuration and generates the OAuth2 authorization url and user bind code that tie a DingTalk identity to the current user.
- exposure: authenticated

### aliyun-sms-notifier
- contract: Lists the SMS sign labels and SMS template labels available through an Aliyun SMS configuration.
- exposure: authenticated

### wechat-notifier
- contract: Lists the WeChat corporate tags, departments and users reachable through a WeChat configuration and generates the OAuth2 authorization url and user bind code that tie a WeChat identity to the current user.
- exposure: authenticated

### dashboard-metrics
- contract: Lists the dashboard definitions and their objects and measurements, and streams measurement values for a dashboard, object, measurement and dimension, either real-time or in bulk.
- exposure: authenticated

### access-log
- contract: Queries the recorded HTTP access log entries (url, method, action, ip and result) that the access-logger captures.
- exposure: authenticated

### system-log
- contract: Queries the platform's system log entries.
- exposure: authenticated

### system-configuration
- contract: Reads and saves the scoped system configuration values, distinguishing public-access scopes (like front-end and access-path configuration) from scopes that require an operator.
- exposure: public for public-access scopes, authenticated for the rest

### system-resources
- contract: Lists the platform's resources (admin only) and serves TypeScript declaration resources for the front-end.
- exposure: authenticated

### command-support
- contract: Lists the internal command services and their command metadata and reports whether a service id has a command support.
- exposure: authenticated

### relation-management
- contract: Maintains typed relations between platform objects (a relation binds an object type and id to a target type and id), queries related objects and the relation type definitions, and validates a relation id.
- exposure: authenticated

### file-management
- contract: Uploads files into the file manager, fetches a stored file (a public file is served directly; otherwise the request must carry the file access key or a signed-in user), and deletes stored files.
- exposure: authenticated (upload), public for file fetch subject to the file's access rule

### cluster-info
- contract: Reports the server nodes of the current cluster.
- exposure: authenticated

### system-info
- contract: Reports the platform version and the API base path information.
- exposure: public

### maintenance-diagnostics
- contract: Presents the maintenance diagnostics console that exports a device operation log file content by path, previews a notification webhook by fetching its url and returning the status and body, and runs a gateway ping diagnostic against a target host.
- exposure: public

## Systems

### authentication mechanism - hsweb authorization
- description: AOP-based authorization that enforces the resource, query/save/delete action and merged-ignore rules on every handler; the seeded `admin` username is allowed every action.

### session mechanism - hsweb user-token
- description: Login tokens generated on authorize and resolved from the `X-Access-Token` header (or Basic authorization header); token lifecycle, per-user token lists and token states are managed through Redis-backed token storage.

### reactive REST framework - hsweb CRUD
- description: The reactive CRUD controllers expose the standard query/save/update/delete endpoint family per resource entity; responses are wrapped in the ResponseMessage envelope, CORS is enabled, and every request is access-logged.

### persistence mechanism - PostgreSQL via R2DBC
- description: All relational entities are stored in a single PostgreSQL schema (public) using the easyorm mapping layer, which creates the tables automatically at startup.

### time-series mechanism - Elasticsearch
- description: Device message data (properties, events and logs) and the platform logs are written to Elasticsearch indices that roll over by month.

### cache mechanism - Redis
- description: Used as the hsweb cache backend, the captcha store and the user-token store; also hosts the cluster-level data of the device registry and message distribution.

### file storage mechanism - hsweb file manager
- description: Uploaded files are stored under the file-manager storage base path and fetched through the file endpoints, optionally guarded by an access key or the current user.

### protocol loading mechanism - JetLinks protocol supports
- description: Protocol packages are resolved from their configuration: a location that starts with `http` is downloaded and cached as a jar under the protocol temp path, otherwise a file id is read through the file manager; loaded protocol packages are exposed as protocol supports with transports and metadata.

### device connectivity mechanism - JetLinks device registry and network
- description: The device registry and session manager track connected devices across the cluster; network components and device gateways bind the platform to real transports (TCP, MQTT, HTTP and others) and carry messages to the device message pipeline.

### rule engine mechanism - JetLinks scene and alarm engine
- description: Scenes and alarms are compiled and executed by the rule engine; alarms raise records that are handled and written to history.

### notification mechanism - JetLinks notifier dispatch
- description: The notifier manager dispatches a send by notify type and provider over a rendered template and context, producing delivery history and per-user notifications.

### dashboard mechanism - JetLinks dashboard manager
- description: The dashboard manager exposes definitions, objects and measurements whose values are computed over the time-series data.

### web storefront - Vue single-page application behind nginx
- description: A separate UI container serves the Vue console and proxies its API requests to the platform; the console authenticates with the token header and calls the same JSON API.

### api documentation - springdoc and knife4j
- description: The OpenAPI groups of the platform are rendered at the doc page and swagger ui, one group per module area (device, rule engine, notify, device access, system management).

### cluster mechanism - JetLinks cluster manager
- description: The cluster manager tracks the HA server nodes and distributes device sessions, cached data and time-series writes across the cluster nodes.

## Roles

- admin: the seeded super administrator; the platform grants this username every permission regardless of configured grants, and the deployment docs give the initial credentials.
- platform user: a regular operator created through user administration, whose access is composed from granted permissions, role dimensions and organisation dimensions.
- third-party identity: a DingTalk or WeChat identity that can be bound to a platform user and used through the notifier OAuth2 flows.

## Service-system mapping

- login-and-authorize relies on the authentication mechanism and the session mechanism for issuing tokens.
- user-token-session relies on the session mechanism and the cache mechanism for token storage.
- login-captcha relies on the cache mechanism and the authentication mechanism for verification during login.
- current-user-profile relies on the persistence mechanism for the user detail and settings records.
- user-administration relies on the persistence mechanism and the authentication mechanism for user records and permission checks.
- role-management relies on the persistence mechanism for roles and user bindings.
- role-group-management relies on the persistence mechanism for role groups.
- permission-catalog relies on the persistence mechanism for the permission records.
- menu-management relies on the persistence mechanism for menus and the authentication mechanism for per-user menus.
- organization-management relies on the persistence mechanism for organisations and user bindings.
- authorization-assignment relies on the persistence mechanism and the authentication mechanism for grant records.
- third-party-user-binding relies on the persistence mechanism for the bind records.
- device-product-management relies on the persistence mechanism and the protocol loading mechanism for product records and protocol metadata.
- device-category relies on the persistence mechanism for categories.
- device-instance-management relies on the persistence mechanism, the device connectivity mechanism and the file storage mechanism for device records, states and excel imports.
- device-data-query relies on the time-series mechanism for property, event and log history.
- device-command-and-control relies on the device connectivity mechanism for message sending.
- gateway-device-management relies on the persistence mechanism and the device connectivity mechanism for parent-child bindings.
- device-metadata-mapping relies on the persistence mechanism for mapping rules.
- transparent-message-codec relies on the persistence mechanism for codec rules.
- device-gateway-access relies on the device connectivity mechanism and the network mechanism for gateways and sessions.
- network-component-management relies on the network mechanism for the network components.
- network-certificate-management relies on the persistence mechanism and the file storage mechanism for certificates.
- network-resource-monitoring relies on the network mechanism and the cluster mechanism for alive resources.
- protocol-management relies on the protocol loading mechanism and the persistence mechanism for protocol definitions.
- protocol-codec-debug relies on the protocol loading mechanism for on-the-fly protocol loading.
- scene-automation relies on the rule engine mechanism for scene execution.
- scene-modeling relies on the rule engine mechanism for trigger and action definitions.
- alarm-configuration relies on the persistence mechanism and the rule engine mechanism for alarm configs and levels.
- alarm-records relies on the persistence mechanism and the rule engine mechanism for alarm records and handling.
- alarm-history relies on the persistence mechanism for alarm history.
- alarm-rule-binding relies on the persistence mechanism for alarm-rule bindings.
- notifier-configuration relies on the persistence mechanism and the notification mechanism for notifier configs.
- notifier-template relies on the persistence mechanism and the notification mechanism for templates.
- notifier-sending relies on the notification mechanism for delivery.
- notification-subscription relies on the persistence mechanism for subscriptions and inbox records.
- notify-channel-configuration relies on the persistence mechanism and the notification mechanism for channels.
- notify-history relies on the persistence mechanism for delivery history.
- dingtalk-notifier relies on the notification mechanism and the authentication mechanism for OAuth2 flows.
- aliyun-sms-notifier relies on the notification mechanism for sign and template listings.
- wechat-notifier relies on the notification mechanism and the authentication mechanism for OAuth2 flows.
- dashboard-metrics relies on the dashboard mechanism and the time-series mechanism for measurement values.
- access-log relies on the time-series mechanism for access log entries.
- system-log relies on the time-series mechanism for system log entries.
- system-configuration relies on the persistence mechanism and the cache mechanism for scoped values.
- system-resources relies on the authentication mechanism for the admin-only resource listing.
- command-support relies on the authentication mechanism for the internal command metadata.
- relation-management relies on the persistence mechanism for relations.
- file-management relies on the file storage mechanism for stored files.
- cluster-info relies on the cluster mechanism for node listing.
- system-info is presented by the web storefront and served without the session mechanism.
- maintenance-diagnostics is presented through the web storefront and served without the session mechanism.