# L1 profile - `siyucms-001` (`Weak Credentials`)

The target unit is `Service:admin-authentication`; connected units and the session mechanism are described below.

## Render block

```
unit kind: Service
spine (present keys): ['api_paradigm', 'auth_methods', 'business_function', 'exposure', 'service_contract']
outgoing edges:
  - DEPENDS_ON: ['AuthenticationMechanism -> kind=AuthenticationMechanism; discriminator=__singleton__; exposure=none']
  - EXPOSED_VIA: ['WebPresentation -> kind=WebPresentation; discriminator=admin-authentication::login-shell; exposure=public']
data items:
  - CONSUMES: name=admin_credential; type=credential; sensitivity=high; fields=__token__,password,username,vercode; notes=The caller-supplied username and password verified against the seeded tp_admin table
  - PRODUCES: name=authenticated_session; type=session; sensitivity=high; fields=admin_id,rules,username; notes=The PHP session opened on a successful match
data relationships:
  - DERIVED_FROM: authenticated_session -> admin_credential (predicate: verified_against_seeded_row)
cooperating systems: (none)
aggregated endpoints:
  - method=GET; path=/admin/index/index.html; baseurl=http://web:80; service_slug=admin-authentication
  - method=GET; path=/admin/login/index.html; baseurl=http://web:80; service_slug=admin-authentication
  - method=POST; path=/admin/login/checkLogin.html; baseurl=http://web:80; service_slug=admin-authentication
```

## Field notes

- Unit identity: `Service:admin-authentication` (key `business_function_slug = admin-authentication`).
