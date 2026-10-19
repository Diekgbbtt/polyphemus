# Account Takeover Chains

Account takeover is a destination, not a class: every entry below is a primitive that becomes a finding only when its terminal proof reaches a second account from the attacker's own session.
This reference is the cross-class catalogue the authorization classes and the identity classes read at their chaining step, and it is kept here because the proof is the methodology's own proof pair.
The catalogue completes when a chain names its primitive, its failing clause, its owning skill, and the terminal state change that demonstrates the takeover.

## The Terminal Proof

- The takeover of a second account you do not control, from the attacker's own session, address, or device.
- A path that only locks the attacker out of the attacker's own account is not a standalone finding.
- A path that needs the victim's password and session together is not a standalone finding.
- A primitive alone is a component; the chain is filed only when its terminal state change completes.
- Blind steps need an out-of-band confirmation, because a reflected value proves nothing about where the token actually arrived.

## The Primitive Catalogue

- **Reset-link poisoning through a link-generating oracle**: the mailer builds the reset link from a caller-influenced host or authority value, so the link points at a destination the attacker controls.
  The failing clause is that the link-generating oracle reads its own address from the request rather than from configuration; `header-injection` owns the authority-family step and `account-recovery` owns the flow.
  The terminal proof is the link arriving at a destination the attacker controls, read from the delivery itself rather than inferred from the reflected value.

- **Token leakage through navigation provenance or a redirect hop**: the reset page loads an off-origin resource or bounces through a redirect while the token stays in the address, so the token reaches a third party.
  The failing clause is that a sensitive value stays in a location the page itself discloses to other origins; `open-redirect` and `proxy-techniques-redirect-chain` own the hop, and `information-disclosure` owns the provenance read.
  The terminal proof is the token read at a destination the attacker controls, captured from the outbound request rather than assumed.

- **Weak or predictable reset token**: the issued token carries less entropy than the strong-randomness bound, or follows a derivable pattern.
  The failing clause is that an issued artifact must be unguessable; `crypto-weakness` and its `crypto-predictable-token` leaf own the entropy adjudication, and `account-recovery` owns the flow.
  The terminal proof is a fresh token guessed after the entropy sample, redeemed in the normal flow, with the sample recorded beside it.

- **Token lifetime, reuse, and cross-account binding**: the token does not expire, survives its own use, survives the issuance of a successor, or resets an account other than the one it was issued to.
  The failing clause is that a recovery token is single-use, short-lived, and bound to one identity; `account-recovery` owns the flow and `idor` owns the cross-account binding verdict.
  The terminal proof is the reset completing for the second account, or the superseded token still redeeming after a successor was issued.

- **Contact-field change without re-authentication**: the change commits with no credential challenge and no confirmation delivered to the previous address, so the reset lands at the attacker's mailbox.
  The failing clause is that a security-relevant contact change re-authenticates the caller and notifies the old contact; `idor` or `mass-assignment` owns the write verdict, and `account-recovery` owns the reset that follows.
  The terminal proof is the reset link arriving at the attacker's address and the login completing with the new credential.

- **Token or claim forgery**: the verification key basis resolves from caller-influenced input, the algorithm is stripped, or the signing secret is weak, so a token naming the victim verifies.
  The failing clause is that the token's integrity rests on material the caller cannot influence; `authentication-jwt` owns the JWT-specific step and `crypto-weakness` owns the abstract key-basis clause.
  The terminal proof is a privileged action performed under the second identity, because decoding or forging alone is not impact.

- **Credential change without step-up**: the credential-change endpoint accepts a new credential from a session alone, with no current-credential or second-factor challenge.
  The failing clause is that a credential change re-authenticates the caller; `session-management` owns the session clause and `mfa-bypass` owns the second-factor clause.
  The terminal proof is a clean login with the new credential from a fresh client, which turns a transient session read into durable ownership.

- **Second-factor enforcement gaps**: the second factor is required at one transition and skipped at another, replayed, or not invalidated after use.
  The failing clause is that the second factor is enforced on every sensitive transition; `mfa-bypass` owns the procedure.
  The terminal proof is the sensitive transition completing without the factor, under the second account.

- **Recovery-answer abuse**: the recovery answers carry low entropy, are not throttled, or are returned or validated client-side.
  The failing clause is that a recovery secret is high-entropy, throttled, and validated server-side; `account-recovery` owns the flow, `weak-credential-discovery` owns the guessing and its rate-limit read, and `rate-limit-bypass` owns the limiter verdict.
  The terminal proof is the recovery flow completing into a session on the second account.

- **Claimed host inside a redirect allowlist**: an authorization redirect accepts a host the attacker can claim, so the code or token lands on attacker infrastructure.
  The failing clause is that every host in a redirect allowlist is one the application controls; `subdomain-takeover` owns the claim and `oauth` owns the redirect step.
  The terminal proof is the code or token arriving at the claimed host and exchanging for the second account's authority.

- **Pre-account seeding**: a pending, invited, or unverified identity accepts a controlled contact value, and the victim later completes the flow into the seeded state.
  The failing clause is that an unverified identity accepts no contact value it did not itself confirm; `account-recovery` owns the flow and `weak-credential-discovery` owns the exposed-identity read.
  The terminal proof is the victim's own login landing in the account the attacker seeded.

- **Passwordless or magic-link abuse by identifier**: the link is bound to a caller-supplied identifier rather than to the delivery channel, so it redeems for an identity the attacker named.
  The failing clause is that a passwordless link binds to the channel that delivered it; `account-recovery` owns the flow and `idor` owns the identifier-binding verdict.
  The terminal proof is the link redeeming for the second account from the attacker's own client.

## Chain Discipline

- Keep each primitive's verdict separate, so a chain reads as a sequence of decided steps rather than one merged claim.
- Record the terminal state change per chain, because the intermediate primitives are components rather than findings.
- Treat a transient session read as a multiplier only when a credential-change or persistence step completes, which is what turns it into durable ownership.
- Confirm a blind step out of band, and prefer a destination the attacker controls over an inference from the response.

## False Positives

- A value reflected in a response where the link destination is pinned server-side, which the delivery itself disproves.
- A token-shaped substring inside an error or claims body, which is not a usable token.
- A reset flow that requires the victim's existing credential beside the token, which is not a takeover primitive.
- A link that redeems only for the account that requested it, confirmed by a second-account attempt.
- A self-lockout that never reaches a second account.

## Delegation

- The control pair, the second-principal discipline, and the proof pair are owned by this skill.
- Each primitive's mechanism stays with its owning class named above; this reference records only the chain and the terminal proof.
- The identity-hint and authority-family steps are named at the classes that own them rather than restated here.
