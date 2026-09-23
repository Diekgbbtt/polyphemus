---
name: windows-trusts
description: AD domain and forest trusts — child-to-parent, SID history, ExtraSid, SID filtering, linked SQL, Kerberoast across domains, DCSync of krbtgt. Use when more than one domain or a trust object is in scope.
metadata:
  version: '1.0'
---

# Domain and forest trusts

## Map trusts

```
nltest /domain_trusts
ldapsearch ... '(objectClass=trustedDomain)'
Get-ADTrust  # if WinRM on a DC
bloodhound-python -c Trusts,ACL,ObjectProps
```

Record: direction (inbound/outbound/bidirectional), type (parent-child, forest, external, shortcut), SID filtering, TGT delegation flags.

## Child → parent (typical)

A child Domain Admin is often enough to compromise the parent:

- **SID History / ExtraSids:** forge a TGT for a child user with parent `Enterprise Admins` SID (`S-1-5-21-<parent>-519`) if SID filtering is off (default parent-child). `ticketer.py -extra-sid` / Rubeus `/sids:`.
- **Unconstrained delegation** on a child DC + coerce parent DC.
- **Trust key:** `secretsdump` DCSync `krbtgt` or the trust TDO (`trusteddomain` object) → inter-realm TGT.
- **Writable parent objects** via ACLs (rare).

## Forest trust

SID filtering is **on** by default (quarantine). ExtraSid to EA usually **fails**. Look instead for:

- Forest trust with **TGT delegation** enabled.
- **MSSQL links** (`windows-mssql`) across forests.
- **SQL/IIS** in the other forest with reused passwords/hashes (`windows-lateral`).
- **ADCS** in the other forest (ESC8 / ESC1) if you can coerce or enroll.
- **Unconstrained delegation** across the trust.
- Shared credential / same `krbtgt` (never) or copied admins.

## External / shortcut trusts

Treat as limited. Kerberoast `GetUserSPNs.py -target-domain other.domain`. Password reuse of roasted hashes across forests is a finding if the same NT hash works (PTH), not if you cracked it.

## DCSync / krbtgt

Parent `krbtgt` ⇒ golden ticket for the parent. Child `krbtgt` does not grant parent DA if SID filtering works.

```
secretsdump.py '<child-domain>/<da>:<pass>@<child-dc>' -just-dc-user krbtgt
# trust keys:
secretsdump.py ... -just-dc | grep -i trusted
```

## Exchange / ADFS / Azure

Trust to Azure AD / ADFS is not a classic forest trust. Token-signing certs and Hybrid PTA agents are separate — record if you see ADFS or Azure AD Connect on a host (`windows-privesc` on that box).

## Extra

- **SID filtering bypass** research (CVE-class) — only if the DC is unpatched and you have a cite.
- **Selective authentication** on forest trusts: you may only reach allowed computers.
- Always keep attacks **in the project scope CIDR/domains**; do not follow trusts out of scope.
