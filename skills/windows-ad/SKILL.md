---
name: windows-ad
description: Windows / Active Directory attack methodology. Use for SMB, LDAP, Kerberos, WinRM, RDP, MSSQL, ADCS, RPC, or domain-joined hosts. Load sibling windows-* skills for the current vector.
metadata:
  version: '1.0'
---

# Windows / Active Directory

Authorized Windows and AD testing. Work **this attack-surface item** (host, port, or service), not the whole forest at once. Load a sibling skill before each vector. Record confirmed issues with `judge_and_record_finding` (command + output as proof). Record hashes and tickets as domain knowledge; do **not** crack them unless a project secret or operator note says to.

Placeholders: `<ip>`, `<dc-ip>`, `<domain>` (DNS), `<DOMAIN>` (NETBIOS), `<user>`, `<pass>`, `<hash>`.

**Tools:** `run_nxc` (NetExec; prefer over CrackMapExec), `run_python` (Impacket, Certipy, BloodHound.py), `run_bash` (nmap NSE, ldapsearch, rpcclient). Do not re-run range-wide nmap or `-p-` if gather already listed ports.

## Skill map

Load the matching skill, then execute. Do not skip a skill because the item is “only a port” — ports imply protocols.

| Item / signal | Load | First actions |
|---|---|---|
| 445 / smb / signing | `windows-smb`, `windows-ad-unauth` | Identity, null/guest, shares, signing |
| 88 / kerberos | `windows-kerberos`, `windows-ad-unauth` | AS-REP, krb5-enum-users, GetNPUsers |
| 389/636/3268 / ldap | `windows-ldap-acl`, `windows-ad-unauth` | Anonymous bind, naming contexts |
| 1433 / mssql | `windows-mssql` | nxc mssql, links, impersonate |
| 5985/5986 / winrm, 3389 / rdp | `windows-lateral` | Auth with secrets only |
| 80/443 on a Windows host, IIS, `.asp` | `windows-privesc` | Upload / web shells only if in scope |
| ADCS / 80 certsrv / 445 on CA | `windows-adcs` | `certipy find` (auth) or ESC8 relay notes |
| Unsigned SMB + listener position | `windows-coerce-relay` | Relay only to unsigned targets |
| Domain user/password in env | `windows-ad-auth` then BloodHound / Kerberoast / ACL | |
| Child/parent/forest/trust | `windows-trusts` | |
| Local admin / SeImpersonate / service | `windows-privesc` | |

Unauthenticated work **always first**. Authenticated work only when project secrets or previously recorded credentials exist. Coercion/poisoning needs a network position you control.

## Findings vs notes

- **Finding:** anonymous listing, SMB signing disabled, AS-REP roastable user (hash recorded), Kerberoastable SPN, ESC1–ESC8 with proof, unconstrained delegation, RBCD you can abuse, DCSync rights, cleartext in description, MSSQL `xp_cmdshell`, IIS unauth upload.
- **Domain knowledge:** user lists, share names, BloodHound zip path, hashes, ticket files, CA name. Not a finding by itself.
- Do not file “port open” as a finding. Do not spray passwords against lockout-prone policies.

## Order (default)

1. Identity: `run_nxc` smb on the host (name, domain, signing, SMBv1).
2. Unauth enum: users/shares/RPC/LDAP null bind (`windows-ad-unauth`).
3. Kerberos without a password (`windows-kerberos`).
4. If secrets exist: LDAP dump, Kerberoast, BloodHound, Certipy, MSSQL (`windows-ad-auth` + specialist skills).
5. Abuse only what you proved: ACL, delegation, ADCS, relay, local privesc, then lateral (`windows-lateral`).
6. Trusts last (`windows-trusts`).

## Sibling skills

`windows-ad-unauth`, `windows-ad-auth`, `windows-smb`, `windows-kerberos`, `windows-ldap-acl`, `windows-adcs`, `windows-mssql`, `windows-coerce-relay`, `windows-privesc`, `windows-lateral`, `windows-trusts`.
