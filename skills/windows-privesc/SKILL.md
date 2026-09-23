---
name: windows-privesc
description: Windows local privilege escalation — SeImpersonate/potatoes, PrintNightmare, unquoted services, AlwaysInstallElevated, IIS/ASP upload, KrbRelayUp, service DLL hijack. Use on a foothold or WinRM/RDP session.
metadata:
  version: '1.0'
---

# Windows local privilege escalation

You already have a shell or WinRM as a low-privileged user (IIS app pool, SQL service, workstation user). Enumerate, then pick **one** reliable primitive.

## Token privileges

```
whoami /priv
whoami /groups
```

**SeImpersonatePrivilege / SeAssignPrimaryToken** (IIS, SQL, NETWORK SERVICE):

- PrintSpoofer / GodPotato / SweetPotato / RogueWinRM — version-dependent.
- `nxc smb <ip> -u <user> -p '<pass>' -M printspoofer` or run the potato **on the host**.
- KrbRelayUp (RBCD from a domain-joined box as SYSTEM path) if potatoes fail.

**SeBackup / SeRestore:** read SAM/SECURITY/NTDS (`reg save`, `diskshadow`). Backup Operators → `windows-ldap-acl`.

**SeDebug:** dump LSASS (`windows-lateral`).

**SeLoadDriver / SeTakeOwnership / SeTcb:** rarer; record the privilege as a finding even before exploit.

## PrintNightmare (CVE-2021-1675 / 34527)

```
nxc smb <ip> -u <user> -p '<pass>' -M printnightmare
# or SharpPrintNightmare / CVE-2021-1675.py with a share you host
```

Needs spooler + unpatched. Unauth variant is uncommon; usually a domain user.

## Service / install abuses

- Unquoted service path with writable directory.
- Weak service binary / `binPath` ACL (`sc qc`, `accesschk`).
- **AlwaysInstallElevated** (HKLM+HKCU `AlwaysInstallElevated=1`) → MSI as SYSTEM.
- Scheduled task writable by the user (`schtasks /query /fo LIST /v`).
- DLL hijack of a SYSTEM service (missing DLL in writable dir).
- **Autoruns** writable folders in PATH.

## IIS / HTTP on Windows

If the surface is IIS and unauthenticated (or low-priv) **upload** of `.asp` / `.aspx` / `.ashx` is allowed:

- Upload a **minimal proof** page that prints `whoami` (not a full backdoor).
- App pool identity often has SeImpersonate → potato.
- `web.config` connection strings, ViewState keys, machineKey.

Do not deploy reverse shells unless the operator asked for interactive access; `whoami` + `hostname` is enough proof.

## KrbRelayUp / local RBCD

On a domain-joined workstation as a standard user: coerce the machine to LDAP, write RBCD to itself, `S4U` to Administrator on **that host**. Needs MAQ or machine-account create. Complements potatoes when SeImpersonate is missing.

## Credentials on disk

```
cmdkey /list
dir /s unattend.xml, sysprep.inf, *.kdbx, web.config
reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\CredentialsDelegation
# GPP leftover, autologon: HKLM\...\Winlogon DefaultPassword
```

LAPS/gMSA are domain (`windows-ad-auth`), not local files.

## Kernel / old CVEs

Only if `systeminfo` shows a clearly unpatched build **and** a public EoP matches. Prefer misconfig (services, tokens) over kernel exploits.

## After SYSTEM

Dump SAM/LSA, LSASS (`lsassy` from another host if you now have admin), then `windows-lateral`. Do not disable Defender or add persistence by default.
