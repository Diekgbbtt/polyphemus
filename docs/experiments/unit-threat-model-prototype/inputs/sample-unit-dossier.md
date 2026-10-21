# Sample unit dossier - prototype input

*Provenance: extracted 2026-10-15 from a previous hunting execution's artifacts in the main checkout: `data/ed6283f5-ced1-40b9-a810-38e3afad7147/hunting/orchestration/hunt_configs/consumed/*.yaml` (the White Jotter target, a Spring Boot + Vue SPA application at `http://dj-viscon-workshop-1.vsos.ethz.ch`). Projections only; no HTTP-history database is present in this checkout, so the HTTP-read step must be recorded as the reads/probes that would be run.*

## 1. The unit under analysis

```yaml
unit_id: Service:article-publishing
kind: Service
business_function_slug: article-publishing
service_contract: Saves a jotter article with its title, markdown source, rendered html, abstract, cover reference and date.
exposure: authenticated
aggregated_endpoints:
  - GET /admin/content/editor at http://dj-viscon-workshop-1.vsos.ethz.ch
edges:
  - EXPOSED_VIA WebPresentation:__singleton__ (Vue SPA, cleartext http://)
cooperating_systems: []
```

## 2. Connected technical systems

```yaml
unit_id: WebPresentation:__singleton__
kind: WebPresentation
description: "Vue SPA; root HTML shell at / serves 白卷 - White Jotter; JS bundle exposes client routes /admin, /admin/dashboard, /admin/content/editor, /login, /authentication, /register, /jotter, /jotter/article, /library, /home, /menu, /index and an /api namespace; origin sets no CSP / X-Content-Type-Options / X-Frame-Options / Referrer-Policy; nginx/1.30.1; all URLs cleartext http."
baseurl: http://dj-viscon-workshop-1.vsos.ethz.ch
exposed_services:
  - account-registration (public)
  - account-sign-in (public)
  - article-browsing (public)
  - article-publishing (authenticated)
  - book-catalog-browsing (public)
  - menu-provisioning (authenticated)
  - register (public)
  - sign-in (public)
aggregated_endpoints:
  - GET /admin/content/editor (article-publishing)
  - GET /authentication (account-sign-in, sign-in)
  - GET /jotter/article (article-browsing)
  - GET /jotter (article-browsing)
  - GET /library (book-catalog-browsing)
  - GET /login (account-sign-in, sign-in)
  - GET /menu (menu-provisioning)
  - GET /register (account-registration, register)
```

```yaml
unit_id: AuthenticationMechanism:__singleton__
kind: AuthenticationMechanism
description: Client-side authentication and registration routes (/login, /authentication, /register) present in the SPA bundle, served over cleartext http://; the actual credential verification mechanism (session, token, or other) is not yet evidenced.
baseurl: http://dj-viscon-workshop-1.vsos.ethz.ch
cooperating_services:
  - account-registration (public)
  - account-sign-in (public)
  - register (public)
  - sign-in (public)
aggregated_endpoints:
  - GET /authentication (account-sign-in, sign-in)
  - GET /login (account-sign-in, sign-in)
  - GET /register (account-registration, register)
assignable_role_vocabulary:
  - sysadmin (system administrator)
  - contentmanager (content administrator)
  - visitor
  - test
  - seeded accounts
exposure_surface: WebPresentation:__singleton__ (Vue SPA, cleartext http, no CSP / X-Frame-Options / X-Content-Type-Options / Referrer-Policy)
```

```yaml
unit_id: AuthorizationSystem:__singleton__
kind: AuthorizationSystem
roles:
  - sysadmin (system administrator)
  - contentmanager (content administrator)
  - visitor
  - test
  - seeded accounts
guarded_services:
  - user-administration
  - user-profile-editing
  - user-status-control
  - user-password-reset
  - role-catalog
  - role-editing
  - role-status-control
  - permission-catalog
  - role-menu-assignment
  - menu-provisioning
  - book-record-management
  - book-record-removal
  - book-cover-upload
  - article-publishing
  - article-removal
exposure_surface: WebPresentation:__singleton__ (Vue SPA, cleartext http, no CSP / X-Frame-Options / X-Content-Type-Options / Referrer-Policy)
cooperating_systems:
  - AuthenticationMechanism:__singleton__ (credential verification mechanism not yet evidenced)
  - WebPresentation:__singleton__
  - IdentificationSystem:__singleton__
projection_notes: Unit projection carried no spine/edges/data-items/cooperating-systems; the roles property (scaffold) and the guarded services' binary authenticated exposure are the observed grounding.
```

```yaml
unit_id: IdentificationSystem:__singleton__
kind: IdentificationSystem
projection_notes: No observed spine/edges/data-items/cooperating-systems/aggregated-endpoints; scaffold-inferred. graph_view confirmed the node has no relationships and no service carries an IDENTIFIED_BY edge to it - reduced grounding.
identity_bearing_services:
  - 'account-sign-in (public): keeps the signed-in identity across visits'
  - 'sign-in (public): starts the session for an existing account holder'
  - 'account-registration (public): binds any roles submitted with the registration to the new account'
  - 'user-administration (authenticated): lists all user accounts together with the roles bound to each account'
  - 'user-profile-editing (authenticated): rebinds the roles assigned to an account'
role_vocabulary:
  - sysadmin (system administrator)
  - contentmanager (content administrator)
  - visitor
  - test
  - seeded accounts
exposure_surface: WebPresentation:__singleton__ (Vue SPA, cleartext http, no CSP / X-Frame-Options / X-Content-Type-Options / Referrer-Policy)
```

## 3. Related services (contracts)

```yaml
- unit_id: Service:account-registration
  service_contract: Creates a new user account from the submitted credentials and profile details, hashing the password with a freshly generated salt and enabling the account immediately. The flow rejects empty credentials and duplicate usernames, and binds any roles submitted with the registration to the new account.
  exposure: public
  aggregated_endpoints: [GET /register]
- unit_id: Service:account-sign-in
  service_contract: Verifies submitted credentials, then starts the session for the existing account holder. (Card not extracted; endpoint GET /login.)
  exposure: public
  aggregated_endpoints: [GET /login]
- unit_id: Service:article-browsing
  service_contract: Lists jotter articles newest first in pages and serves a single article by its identifier for reading.
  exposure: public
  aggregated_endpoints: [GET /jotter, GET /jotter/article]
- unit_id: Service:book-catalog-browsing
  service_contract: Lists the book catalog either in full or filtered to the books of a chosen category, newest records first.
  exposure: public
  aggregated_endpoints: [GET /library]
- unit_id: Service:menu-provisioning
  service_contract: (Not extracted; linked by WebPresentation at GET /menu, authenticated.)
```

## 4. Observed environment traits

- All observed URLs are cleartext `http://`; TLS is not evidenced on the surface.
- Server header: `nginx/1.30.1`; the SPA is Vue; the root shell serves 白卷 - White Jotter.
- The origin sets no `Content-Security-Policy`, no `X-Content-Type-Options`, no `X-Frame-Options`, no `Referrer-Policy`.
- A client-side `/api` namespace and admin routes ship in the SPA bundle.
- Roles observed in the scaffold: sysadmin, contentmanager, visitor, test, seeded accounts.
- The article-publishing submission endpoint is NOT evidenced at L0; only the SPA route `GET /admin/content/editor` is.

## 5. Evidence gaps (to be recorded as reads/probes, not invented)

- HTTP-history records for `/admin/content/editor`, `/api` calls under it, and the article submission request are not available in this checkout.
- The credential verification mechanism (session cookie or token), the authorization enforcement point, and the persistence layer are not evidenced.
