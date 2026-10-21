# header-injection - high-value targets (extracted for the threat-modeller migration)

## High-Value Targets

- Password-reset and account-recovery flows (Host header determines the link sent to the user)
- OAuth / SSO redirect endpoints (`Location`, `redirect_uri` echoes)
- Auth gateways that trust `X-Forwarded-For` / `X-Real-IP` for IP allowlists or rate limits
- CDN / WAF caches (poisoning a public cache with a per-user response)
- Multi-tenant routing keyed on Host or `X-Tenant-Id`
- File-download endpoints (`Content-Disposition` filename derived from user input)
- Outbound notification / email systems where user input lands in the message header
