# http-request-smuggling - high-value targets (extracted for the threat-modeller migration)

## High-Value Targets

- Front-end security controls (authentication bypass via desync)
- Endpoints shared by many users (high-traffic APIs, chat, feeds)
- Request capture endpoints (search, logging, analytics)
- Session-sensitive endpoints (auth callbacks, account settings)
- Internal admin interfaces proxied through the same connection pool
