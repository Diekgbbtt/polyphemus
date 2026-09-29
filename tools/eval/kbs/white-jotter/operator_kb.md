# White-Jotter (1.0.0)

## Overview

The deployed application is a personal blog and library platform named White Jotter ("Your Mind Palace").
It is a Spring Boot REST backend (`wj`) that serves a Vue.js single-page application from the same origin, listening on port 8443.
The public storefront offers a book library with category browsing and keyword search, plus a jotter article journal for reading posts.
A role-based back-office lets administrators manage user accounts, roles and permissions, book records and covers, and articles.
Read-heavy listings are served from a Redis cache, and all data persists in a MySQL database.

## Services

### account-registration
- contract: Creates a new user account from the submitted credentials and profile details, hashing the password with a freshly generated salt and enabling the account immediately.
  The flow rejects empty credentials and duplicate usernames, and binds any roles submitted with the registration to the new account.
- exposure: public

### account-sign-in
- contract: Authenticates a visitor against the user store with username and password, keeps the signed-in identity across visits, signs the subject out again, and reports the current authentication status of the request.
- exposure: public

### user-administration
- contract: Lists all user accounts together with the roles bound to each account, for the back-office user management screen.
- exposure: authenticated

### user-profile-editing
- contract: Updates an account's profile contact details and rebinds the roles assigned to that account.
- exposure: authenticated

### user-status-control
- contract: Enables or disables a user account; an account that is disabled is refused at sign-in.
- exposure: authenticated

### user-password-reset
- contract: Resets an account's password to a fixed default value, re-salting the stored credential so the new password is recorded.
- exposure: authenticated

### role-catalog
- contract: Lists the role records together with the permissions and menus each role carries, for the back-office role management screen.
- exposure: authenticated

### role-editing
- contract: Creates a new role or updates an existing role record, and rebinds the role's permission set to the submitted permissions.
- exposure: authenticated

### role-status-control
- contract: Enables or disables a role.
- exposure: authenticated

### permission-catalog
- contract: Publishes the permission records the role editor draws on, each naming a protected management surface.
- exposure: authenticated

### role-menu-assignment
- contract: Rebinds a role's menu set, replacing the previous assignments with the submitted menu identifiers.
- exposure: authenticated

### menu-provisioning
- contract: Serves the navigation menu tree for the currently signed-in user and the menu set belonging to a role, used to build the back-office navigation.
- exposure: authenticated

### book-catalog-browsing
- contract: Lists the book catalog either in full or filtered to the books of a chosen category, newest records first.
- exposure: public

### book-search
- contract: Finds books whose title or author matches a submitted keyword and returns them newest first.
- exposure: public

### book-record-management
- contract: Creates or updates a book record carrying title, author, publication date, press, abstract, cover reference and category.
- exposure: authenticated

### book-record-removal
- contract: Removes a book record by its identifier.
- exposure: authenticated

### book-cover-upload
- contract: Receives an uploaded cover image, stores it under the workspace image folder under a randomized file name, and returns the file reference used to display it.
- exposure: authenticated

### book-cover-serving
- contract: Serves a stored cover image file back to the browser for inline display.
- exposure: public

### article-publishing
- contract: Saves a jotter article with its title, markdown source, rendered html, abstract, cover reference and date.
- exposure: authenticated

### article-removal
- contract: Removes a jotter article by its identifier.
- exposure: authenticated

### article-browsing
- contract: Lists jotter articles newest first in pages and serves a single article by its identifier for reading.
- exposure: public

## Systems

### authentication - shiro session
- description: Apache Shiro authenticates a username and password against the user store with salted password hashing, keeps the authenticated subject in the servlet session, and issues a long-lived remember-me cookie so a signed-in user persists across visits.
- description: The remember-me cookie is issued on sign-in and consumed to restore the identity on later requests.

### authorization - role permission filter
- description: A path-matching servlet filter guards the administration surface: every admin request must come from an authenticated subject, and the requested API is then checked against the permission URLs granted to the subject's roles by prefix matching.
- description: The permission model lives in the database, so which surfaces a role may reach is data, not code.

### persistence - mysql datastore
- description: Spring Data JPA persists the domain in the MySQL database: users, books and categories, jotter articles, and the role, permission and menu tables together with their join tables.
- description: The schema and the seed records are applied at startup, so a fresh deployment starts with a populated catalog and a set of known accounts and roles.

### caching - redis cache
- description: Redis backs the read-heavy surfaces: the book catalog, article pages and individual articles are cached by key and invalidated when the underlying records change.
- description: The book catalog entry is dropped whenever a book is added, updated or deleted, and article pages are dropped whenever an article is saved or removed.

### file storage - cover image store
- description: Uploaded book cover images are written to a server-side image folder and read back from the configured upload directory when the public cover endpoint serves them.
- description: The upload folder and the serve directory are resolved from configuration at runtime.

### presentation - vue single page application
- description: A Vue.js and Element UI single-page application is served as static resources from the same origin, with its axios client sending credentials on every request against the same-origin REST surface.
- description: The back-office routes are added at runtime from the menu tree the menu service returns for the signed-in user.

### operations - actuator management
- description: Spring Boot Actuator exposes the management endpoints on the same port, covering health, info, bean and mapping listings and similar diagnostics.
- description: The environment endpoint is excluded from the exposed set; the remainder is reachable without sign-in.

## Roles

- sysAdmin (system administrator): holds the user, role and content management permissions and the full back-office menu set.
- contentManager (content administrator): holds the content management permission and the book, banner and article management menus.
- visitor: holds no management permission and sees only the home and dashboard menus.
- test: a seeded test role that holds no management permission and sees the home and dashboard menus.
- Seeded accounts: admin (sysAdmin), test (visitor and test), editor (contentManager).

## Service-system mapping

- account-registration relies on the mysql datastore to create the account and its role bindings.
- account-sign-in relies on the shiro session for authentication and on the remember-me cookie for persistence.
- user-administration relies on the mysql datastore and on the role permission filter for access.
- user-profile-editing relies on the mysql datastore for the profile and role binding update and on the role permission filter for access.
- user-status-control relies on the mysql datastore for the enabled flag and on the role permission filter for access.
- user-password-reset relies on the mysql datastore for the re-salted credential and on the role permission filter for access.
- role-catalog relies on the mysql datastore for roles, permissions and menus and on the role permission filter for access.
- role-editing relies on the mysql datastore for the role record and its permission bindings and on the role permission filter for access.
- role-status-control relies on the mysql datastore for the role flag and on the role permission filter for access.
- permission-catalog relies on the mysql datastore for the permission records and on the role permission filter for access.
- role-menu-assignment relies on the mysql datastore for the role menu bindings and on the role permission filter for access.
- menu-provisioning relies on the mysql datastore for the menu tree and on the shiro session to resolve the current user.
- book-catalog-browsing relies on the redis cache for the cached listings and on the mysql datastore for the source records.
- book-search relies on the mysql datastore for the query over titles and authors.
- book-record-management relies on the mysql datastore for the book record and on the redis cache for invalidation, and on the role permission filter for access.
- book-record-removal relies on the mysql datastore for the deletion and on the redis cache for invalidation, and on the role permission filter for access.
- book-cover-upload relies on the cover image store for the uploaded image file and on the role permission filter for access.
- book-cover-serving relies on the cover image store to resolve and serve the stored file.
- article-publishing relies on the mysql datastore for the article and on the redis cache for invalidation, and on the role permission filter for access.
- article-removal relies on the mysql datastore for the deletion and on the redis cache for invalidation, and on the role permission filter for access.
- article-browsing relies on the redis cache for the cached pages and articles and on the mysql datastore for the source records.
- All services are presented through the vue single page application, which sends credentials on every request.