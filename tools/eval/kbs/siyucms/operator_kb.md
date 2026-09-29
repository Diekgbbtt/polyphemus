# SIYUCMS (6.1)

## Overview

SIYUCMS is a ThinkPHP 6 based content management system (CMS) deployed on PHP 7.3
under Apache with a MySQL 5.7 backend. The application ships four multi-app
surfaces served from one document root: the public website (index app), a
parallel mobile website (mobile app), an administrator back office (admin app)
and a JSON member API (api app). The content model is built around reusable
content modules (article, picture, product, download, team, single page) hung
under an unlimited-level category (栏目) tree, each module backed by its own
table plus shared scaffolding tables for fields, dictionaries and permissions.
The default installation is seeded with a company showcase site (about, news,
products, download, team, contact categories) and a set of demo content.

## Services

### site-homepage
- contract: Renders the website home page, applying the configured template and
  mobile-app redirect rule for the active theme.
- exposure: public

### content-search
- contract: Takes a search keyword and renders a search results page scoped to
  the current template.
- exposure: public

### tag-browsing
- contract: Lists content carrying a given tag for a given content module.
- exposure: public

### message-submission
- contract: Accepts a posted 留言/投稿 (guestbook/submission) form and inserts it
  into the target content module's table under the selected category, honoring
  required fields and the configured captcha and email-notification switches.
- exposure: public

### content-listing
- contract: Renders the list page of a category for its content module, applying
  the category's list template, dictionary filters and search fields.
- exposure: public

### content-detail
- contract: Renders a single content record's detail page, increments its hit
  counter, and enforces the record's member-type reading permission when the
  field is set.
- exposure: public

### site-captcha
- contract: Generates a captcha image for the front site.
- exposure: public

### member-login
- contract: Authenticates a member by email or mobile plus password and opens a
  web session for the member center, honoring the captcha switch.
- exposure: public

### member-registration
- contract: Registers a new member with email, password and confirmation,
  enforcing password length and email uniqueness, and assigns the default
  member type.
- exposure: public

### member-center-homepage
- contract: Shows the logged-in member's own profile in the member center.
- exposure: authenticated

### member-profile-update
- contract: Updates the member's sex, qq and mobile fields for the logged-in
  member, enforcing mobile uniqueness.
- exposure: authenticated

### member-password-update
- contract: Changes the logged-in member's password after verifying the current
  password and the confirmation match.
- exposure: authenticated

### member-signout
- contract: Ends the member web session and returns to the login page.
- exposure: authenticated

### api-member-login
- contract: Authenticates a member by email or mobile plus password and returns
  a bearer token for subsequent api requests.
- exposure: public

### api-member-registration
- contract: Registers a member by email and password and returns a success
  result; the member then logs in again to obtain a token.
- exposure: public

### api-member-profile-view
- contract: Returns the authenticated member's own profile record joined with
  the member type name.
- exposure: authenticated

### api-member-password-update
- contract: Verifies the original password and sets the new password for the
  authenticated member.
- exposure: authenticated

### api-member-profile-update
- contract: Applies sex, qq and mobile updates to a member profile identified by
  the request, defaulting to the authenticated token subject; enforces mobile
  uniqueness against other members.
- exposure: authenticated

### admin-authentication
- contract: Presents the back-office login page, verifies administrator
  username and password (with captcha and form-token checks driven by system
  settings) and opens the administrator session, then signs the administrator
  out on logout.
- exposure: public

### admin-dashboard
- contract: Shows the back-office dashboard with server and CMS version details
  and recent activity counters, clears the runtime cache, previews a content
  record on the public site, and serves the select2 and linkage ajax data feeds
  used by admin forms.
- exposure: authenticated

### administrator-management
- contract: Manages administrator accounts (管理员列表), including listing,
  creating, editing and deleting accounts and assigning each a role group; the
  built-in super administrator account is protected from deletion.
- exposure: authenticated

### role-permission-management
- contract: Maintains role groups (角色组) and their assignment of menu rules
  (菜单规则), and edits the menu rule tree that drives admin menu display and
  per-action permission checks.
- exposure: authenticated

### admin-log-management
- contract: Reviews the recorded administrator operation log entries (url,
  title, content, ip, user-agent) left by admin activity.
- exposure: authenticated

### system-settings
- contract: Edits the single system settings record covering site identity,
  contact and SEO fields, the front mobile switch, captcha switches, template
  selection, upload limits and the upload driver.
- exposure: authenticated

### mail-configuration
- contract: Configures the SMTP mail server and sender for system mail, saves
  the settings and sends a test mail.
- exposure: authenticated

### sms-configuration
- contract: Configures the Alibaba Cloud SMS credentials, signature and
  template, saves the settings and sends a test short message.
- exposure: authenticated

### database-maintenance
- contract: Lists the application tables, backs them up to the Data directory,
  optimizes and repairs them, and lists, imports, downloads and deletes backup
  files.
- exposure: authenticated

### content-module-management
- contract: Manages the content module registry (模块) where each module maps a
  business model to a data table, inspects existing table structures, creates
  new tables, and generates admin controller code and menu rules for a module.
- exposure: authenticated

### field-management
- contract: Manages the fields (字段) of each content module, altering the
  underlying table columns when fields are added, changed, toggled or removed,
  and grouping fields into field groups.
- exposure: authenticated

### field-group-management
- contract: Manages the field groups that organize a module's form fields.
- exposure: authenticated

### dictionary-type-management
- contract: Manages dictionary types (字典类型) that classify dictionary data.
- exposure: authenticated

### dictionary-data-management
- contract: Manages dictionary data (字典) entries used by select, radio and
  filter fields across modules.
- exposure: authenticated

### category-management
- contract: Manages the unlimited-level category (栏目) tree, moving categories
  under modules, batch-creating categories, and cascading content deletion when
  a category and its children are removed.
- exposure: authenticated

### article-content-management
- contract: Manages article records (文章) with title, content, category,
  images, tags, keywords, template and reading-permission fields.
- exposure: authenticated

### single-page-management
- contract: Manages single-page records (单页) carrying title and content under
  their categories for standalone pages.
- exposure: authenticated

### picture-content-management
- contract: Manages picture records (图片) with title, image, image gallery,
  tags and summary fields.
- exposure: authenticated

### product-content-management
- contract: Manages product records (产品) with title, content, image gallery,
  specifications, tags and summary fields.
- exposure: authenticated

### download-content-management
- contract: Manages download records (下载) with title, content, attachment
  file, tags and summary fields.
- exposure: authenticated

### team-content-management
- contract: Manages team member records (团队) with title, author, source,
  content, image and summary fields.
- exposure: authenticated

### guestbook-management
- contract: Manages submitted 留言 (guestbook message) records received from
  the front site message-submission form.
- exposure: authenticated

### advertisement-management
- contract: Manages advertisement (广告) records with image, thumbnail, link and
  description under an advertisement position.
- exposure: authenticated

### advertisement-type-management
- contract: Manages advertisement positions (广告分组) that advertisements
  belong to.
- exposure: authenticated

### friend-link-management
- contract: Manages friend-link (友情链接) records shown on the site.
- exposure: authenticated

### content-fragment-management
- contract: Manages content fragments (碎片) reused across templates.
- exposure: authenticated

### member-administration
- contract: Manages front members (会员), listing, creating, editing, deleting
  and exporting member accounts and toggling their status and member type.
- exposure: authenticated

### member-type-management
- contract: Manages the member type (会员分组) groups that classify front
  members and gate content reading permission.
- exposure: authenticated

### template-management
- contract: Browses and edits the active theme's html, css and js template
  files with automatic backups, and browses and deletes media files under the
  theme's image directory.
- exposure: authenticated

### media-library-upload
- contract: Receives image and file uploads from the ckeditor, ueditor and
  webuploader editors, handling chunked large-file reassembly, stores uploads
  under date-stamped directories, serves the ueditor configuration and file
  listing actions, and catches remote images by fetching a supplied http(s)
  image URL server-side into the uploads directory.
- exposure: authenticated

### plugin-management
- contract: Lists installed plugins (插件), installs and uninstalls them, and
  reads and saves each plugin's configuration.
- exposure: authenticated

### admin-demo-kit
- contract: Serves the built-in UI kit demo pages showing buttons, icons,
  general elements, modals, timelines and layer windows, including one demo
  form submission.
- exposure: authenticated

## Systems

### authentication - session mechanism
- description: ThinkPHP file-backed sessions (PHPSESSID cookie) authenticate the
  back office and the web member center; the admin middleware requires an admin
  session and the member center requires a member session.

### authentication - jwt mechanism
- description: The api app authenticates members with an HS256 signed JWT
  carrying the member uid, issued for one hour and presented in the token
  request header, validated and signature-verified by the api middleware.

### captcha - captcha mechanism
- description: think-captcha image generation with a server-side check, wired to
  the back-office login and the front message and member forms when enabled by
  system settings; disabled in the deployed seed configuration.

### forms - form-token mechanism
- description: The back-office login additionally verifies a __token__ hidden
  form token as a second layer of the admin login flow.

### authorization - permission mechanism
- description: Rule-based RBAC over role groups and menu rules; each admin
  request is checked against the administrator's assigned rules unless it is on
  the open allowlist or the administrator is the super administrator account.

### storage - file storage mechanism
- description: Uploaded files land on the local public disk under the uploads
  directory in date-stamped folders, with chunked reassembly for large files;
  the system setting can route uploads to a cloud driver (Aliyun OSS or Qiniu).

### integration - remote url fetch mechanism
- description: The ueditor remote image catcher fetches a caller-supplied http(s)
  image URL server-side with a desktop browser user-agent, does not follow
  redirects, applies a short timeout, and stores the response bytes under the
  uploads directory.

### rendering - template mechanism
- description: think-template renders public pages from theme files under the
  template directory, with separate index and mobile view trees; the admin
  template editor reads and writes these files and keeps change backups.

### persistence - database mechanism
- description: ThinkPHP ORM over the MySQL 5.7 database using the tp_ table
  prefix; content modules map one-to-one to tables created by module
  management.

### persistence - database backup mechanism
- description: The database maintenance service dumps, optimizes, repairs and
  restores tables as backup files stored in the Data directory.

### notification - mail mechanism
- description: PHPMailer sends SMTP mail using the smtp configuration group for
  system notifications and test mail.

### notification - sms mechanism
- description: The Alibaba Cloud SMS client (Dysmsapi) sends short messages
  using the sms configuration group.

### caching - cache mechanism
- description: ThinkPHP runtime file caching with a back-office clear action;
  request caching is disabled in the deployed configuration.

### routing - multi-app dispatch mechanism
- description: think-multi-app maps the first URL segment to one of the four
  apps (index, mobile, admin, api) with index as the default app; dynamic
  category routes are registered from the category table.

### scaffolding - form and table builder
- description: FormBuilder, TableBuilder and MakeBuilder generate admin list,
  form and code artifacts from module and field metadata, enabling the content
  module and field services.

### audit - operation log mechanism
- description: The admin middleware records each administrator request to the
  operation log table with url, title, content, ip and user-agent.

## Roles

- super-admin: the built-in administrator account with id 1 that is exempt
  from the permission rule check; the project README documents its default
  credentials.
- admin: back-office operator, session-authenticated and scoped by an assigned
  role group's menu rules.
- member: registered front-end user grouped by member type (普通会员, VIP会员),
  with a status switch controlling login; authenticated by web session on the
  site and by jwt on the api.
- guest: anonymous visitor with access to public content, search, tags, the
  message form, and the registration and login surfaces.

## Service-system mapping

- site-homepage relies on the template mechanism for rendering and the multi-app dispatch mechanism for the index and mobile apps.
- content-search, tag-browsing, content-listing, content-detail rely on the template and database mechanisms.
- content-detail relies on the session mechanism to enforce member-type reading permission.
- message-submission relies on the captcha mechanism and the mail mechanism for its switches, and the database mechanism to store submissions.
- member-login, member-registration, member-center-homepage, member-profile-update, member-password-update, member-signout rely on the session and database mechanisms.
- api-member-login, api-member-registration, api-member-profile-view, api-member-password-update, api-member-profile-update rely on the jwt and database mechanisms.
- admin-authentication relies on the session, captcha and form-token mechanisms.
- admin-dashboard and the admin content and configuration services (administrator-management, role-permission-management, admin-log-management, system-settings, content-module-management, field-management, field-group-management, dictionary-type-management, dictionary-data-management, category-management, article-content-management, single-page-management, picture-content-management, product-content-management, download-content-management, team-content-management, guestbook-management, advertisement-management, advertisement-type-management, friend-link-management, content-fragment-management, member-administration, member-type-management, template-management, media-library-upload, plugin-management) rely on the session and permission mechanisms for access control and the database mechanism for persistence.
- content-module-management and field-management rely on the form and table builder for generated screens and code, and the database mechanism for schema changes.
- media-library-upload relies on the file storage mechanism and the remote url fetch mechanism.
- template-management relies on the template mechanism for theme file editing.
- database-maintenance relies on the database backup mechanism and the persistence mechanism.
- mail-configuration relies on the mail mechanism; sms-configuration relies on the sms mechanism.
- admin-log-management relies on the operation log mechanism.
- admin-dashboard relies on the cache mechanism for cache clearing.
- all services are presented through the multi-app dispatch mechanism on the
  shared web endpoint.