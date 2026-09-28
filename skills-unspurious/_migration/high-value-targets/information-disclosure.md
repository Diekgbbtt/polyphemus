# information-disclosure - high-value targets (extracted for the threat-modeller migration)

## High-Value Surfaces

### Errors and Exceptions

- SQL/ORM errors: reveal table/column names, DBMS, query fragments
- Stack traces: absolute paths, class/method names, framework versions, developer emails
- Template engine probes: `{{7*7}}`, `${7*7}` identify templating stack
- JSON/XML parsers: type mismatches leak internal model names

### Debug and Env Modes

- Debug pages: Django DEBUG, Laravel Telescope, Rails error pages, Flask/Werkzeug debugger, ASP.NET customErrors Off
- Profiler endpoints: `/debug/pprof`, `/actuator`, `/_profiler`, custom `/debug` APIs
- Feature/config toggles exposed in JS or headers

### DVCS and Backups

- DVCS: `/.git/` (HEAD, config, index, objects), `.svn/entries`, `.hg/store` → reconstruct source and secrets
- Backups/temp: `.bak`/`.old`/`~`/`.swp`/`.swo`/`.tmp`/`.orig`, db dumps, zipped deployments
- Build artifacts: dist artifacts containing `.map`, env prints, internal URLs

### Configs and Secrets

- Classic: web.config, appsettings.json, settings.py, config.php, phpinfo.php
- Containers/cloud: Dockerfile, docker-compose.yml, Kubernetes manifests, service account tokens
- Credentials and connection strings; internal hosts and ports; JWT secrets

### API Schemas and Introspection

- OpenAPI/Swagger: `/swagger`, `/api-docs`, `/openapi.json` - enumerate hidden/privileged operations
- GraphQL: introspection enabled; field suggestions; error disclosure via invalid fields
- gRPC: server reflection exposing services/messages

### Client Bundles and Maps

- Source maps (`.map`) reveal original sources, comments, and internal logic
- Client env leakage: `NEXT_PUBLIC_`/`VITE_`/`REACT_APP_` variables; embedded secrets
- `__NEXT_DATA__` and pre-fetched JSON can include internal IDs, flags, or PII

### Headers and Response Metadata

- Fingerprinting: Server, X-Powered-By, X-AspNet-Version
- Tracing: X-Request-Id, traceparent, Server-Timing, debug headers
- Caching oracles: ETag/If-None-Match, Last-Modified/If-Modified-Since, Accept-Ranges/Range

### Storage and Exports

- Public object storage: S3/GCS/Azure blobs with world-readable ACLs or guessable keys
- Signed URLs: long-lived, weakly scoped, re-usable across tenants
- Export/report endpoints returning foreign data sets or unfiltered fields

### Observability and Admin

- Metrics: Prometheus `/metrics` exposing internal hostnames, process args
- Health/config: `/actuator/health`, `/actuator/env`, Spring Boot info endpoints
- Tracing UIs: Jaeger/Zipkin/Kibana/Grafana exposed without auth

### Cross-Origin Signals

- Referrer leakage: missing/weak referrer policy leading to path/query/token leaks to third parties
- CORS: overly permissive Access-Control-Allow-Origin/Expose-Headers revealing data cross-origin; preflight error shapes

### File Metadata

- EXIF, PDF/Office properties: authors, paths, software versions, timestamps, embedded objects

### Cloud Storage

- S3/GCS/Azure: anonymous listing disabled but object reads allowed; metadata headers leak owner/project identifiers
- Pre-signed URLs: audience not bound; observe key scope and lifetime in URL params
