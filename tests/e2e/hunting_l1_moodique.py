"""The rich moodique.com L1 scaffold for the candidates-rewrite e2e tier.

Source of truth: ``/var/.../langfuse-l1-evidence.md`` - the recovered L0/L1 model
of the operator's prior project (moodique.com, a PrestaShop Italian wine
e-commerce) reconstructed from successful Langfuse analysis traces in session
``27386f9c-361d-4084-926f-5e2f5160290d`` (2026-08-02), cross-checked against
the mechanism-typist ``typist-systems-and-edges`` structured outputs, the
assigner ``assigner-aggregates`` proposals and the data_modeller
``data_flows`` / ``data_relationships`` step writes. The scaffold MERGEs the
recovered model into the live neo4j graph for a given ``project_id`` so the
hunting orchestrator's read-only projection grounds on a REAL, detailed L1
(services with contracts, systems with wire witnesses, typed auth/identification
edges, data items with flows, L0 endpoints with headers/parameters) - not the
two-unit synthetic "slug:a/key:b" mini-fixture.

Every node/edge type is authored against the L1 schema (``db/neo4j/l1_schema.py``
+ ``src/polymerhus/analysis/l1_curator.py``): ``L1Service`` keyed on
(business_function_slug, project_id), ``L1System`` keyed on (kind,
discriminator, project_id), ``L1DataItem`` keyed on (item_key, project_id); the
edge families are EXPOSED_VIA / AUTHENTICATED_BY / IDENTIFIED_BY /
SHAPES_DATA_OF / DEPENDS_ON (the ``SYSTEM_EDGE_RELS`` allowlist) and
PRODUCES / CONSUMES (the data-flow families); the DataRelationship kinds are
the six `DATA_RELATIONSHIP_KINDS` allowlist values (the observed ``references``
kind of the live project is an open string and is NOT writable through the L1
sole-writer - it is mapped onto the closest allowlist kind ``SUBSET_OF``, see
the NOTE in section 5 of the evidence file).

The fixture is deliberately rich so the gate's ``build_projection`` resolves
non-empty ``edges``, ``data_items``, ``data_rel_kinds`` and - for the
AuthenticationMechanism System target - ``cooperating_systems`` (the D3
adjacency over the authenticated-by inbound edges).
"""
from __future__ import annotations

# business_function_slug -> service_contract (verbatim from evidence_refs).
SERVICES: dict[str, str] = {
    "catalogue-and-discovery":
        "Browse the full wine catalogue by type, grape, territory, producer, "
        "pairing, and mood",
    "product-page-reviews-wishlist":
        "Product detail pages, reviews and the wishlist area; maintains a "
        "wishlist and owns wishlist entries",
    "gifting-and-b2b":
        "Gift packaging (astuccio, scatola-di-legno, confezione-regalo-per-"
        "bottiglia, shopper-porta-bottiglie-regalo, confezioni-vino-da-6-"
        "bottiglie), corporate gifts (regali-aziendali), B2B/HORECA supplies "
        "(forniture-e-distribuzione-vini-e-distillati) and gift wrapping",
    "sign-in":
        "Authenticate an existing account holder and start their session; "
        "deals in credentials, login, sign-in",
    "customer-registration-and-login":
        "Register a new customer account and log in via the Leo Quick Login "
        "module (leoquicklogin)",
    "cart-and-checkout":
        "Manage the shopping cart (/carrello) and drive the checkout flow",
    "moodclub-loyalty":
        "The MoodClub loyalty programme: Entra nel MoodClub e Scopri i "
        "Vantaggi del Programma Fedeltà",
    "payments-and-shipping":
        "Payment methods (modalita-di-pagamento) and shipping and returns "
        "(spedizioni-e-resi)",
    "promotional-surfaces":
        "Wine offers (offerte-vini) and outlet (outlet-vini) promotional "
        "landing surfaces",
}

# kind -> discriminator -> (exposure, description).
SYSTEMS: dict[str, tuple[list[str], str, str]] = {
    "WebPresentation": (
        ["catalogue-and-discovery::homepage", "catalogue-and-discovery::product-page",
         "catalogue-and-discovery::category-page", "catalogue-and-discovery::category-listing",
         "catalogue-and-discovery::static-page", "catalogue-and-discovery::not-found",
         "catalogue-and-discovery::module-page", "authentication::login-page"],
        "public",
        "The navigable text/html PAGES the storefront renders - PRODUCT/CATEGORY/"
        "LISTING/STATIC/NOT-FOUND/MODULE page clusters grouped by rendered "
        "similarity, plus the authentication login page",
    ),
    "AuthenticationMechanism": (
        ["__singleton__", "prestashop-login"],
        "public",
        "PrestaShop authentication mechanism (login, registration, password-"
        "reset) surfaced via the LeoQuickLogin module; reCAPTCHA-protected, "
        "permissive CORS",
    ),
    "IdentificationSystem": (
        ["__singleton__"],
        "public",
        "PrestaShop session identification: the PrestaShop-adab* cookie "
        "(HttpOnly, Secure, SameSite=Lax) set on all pages",
    ),
    "IntegrationSystem": (
        ["__singleton__"],
        "public",
        "Cross-origin integration + security headers: Access-Control-Allow-"
        "Origin: * on every response, missing CSP/HSTS/X-Frame-Options/"
        "X-Content-Type-Options, custom X-SS timing header",
    ),
}

# service_slug -> [(kind, discriminator, rel), ...]
EDGES: dict[str, list[tuple[str, str, str]]] = {
    "catalogue-and-discovery": [
        ("WebPresentation", "catalogue-and-discovery::homepage", "EXPOSED_VIA"),
        ("WebPresentation", "catalogue-and-discovery::product-page", "EXPOSED_VIA"),
        ("WebPresentation", "catalogue-and-discovery::category-page", "EXPOSED_VIA"),
        ("WebPresentation", "catalogue-and-discovery::category-listing", "EXPOSED_VIA"),
        ("WebPresentation", "catalogue-and-discovery::static-page", "EXPOSED_VIA"),
        ("WebPresentation", "catalogue-and-discovery::not-found", "EXPOSED_VIA"),
        ("WebPresentation", "catalogue-and-discovery::module-page", "EXPOSED_VIA"),
        ("AuthenticationMechanism", "__singleton__", "AUTHENTICATED_BY"),
        ("IdentificationSystem", "__singleton__", "IDENTIFIED_BY"),
        ("IntegrationSystem", "__singleton__", "SHAPES_DATA_OF"),
    ],
    "product-page-reviews-wishlist": [
        ("WebPresentation", "catalogue-and-discovery::product-page", "EXPOSED_VIA"),
        ("IdentificationSystem", "__singleton__", "IDENTIFIED_BY"),
        ("IntegrationSystem", "__singleton__", "SHAPES_DATA_OF"),
    ],
    "sign-in": [
        ("WebPresentation", "authentication::login-page", "EXPOSED_VIA"),
        ("AuthenticationMechanism", "prestashop-login", "AUTHENTICATED_BY"),
        ("IdentificationSystem", "__singleton__", "IDENTIFIED_BY"),
        ("IntegrationSystem", "__singleton__", "SHAPES_DATA_OF"),
    ],
    "cart-and-checkout": [
        ("WebPresentation", "catalogue-and-discovery::module-page", "EXPOSED_VIA"),
    ],
    "moodclub-loyalty": [
        ("WebPresentation", "catalogue-and-discovery::module-page", "EXPOSED_VIA"),
        ("AuthenticationMechanism", "__singleton__", "AUTHENTICATED_BY"),
    ],
    "payments-and-shipping": [
        ("WebPresentation", "catalogue-and-discovery::static-page", "EXPOSED_VIA"),
    ],
    "gifting-and-b2b": [
        ("WebPresentation", "catalogue-and-discovery::category-page", "EXPOSED_VIA"),
    ],
    "promotional-surfaces": [
        ("WebPresentation", "catalogue-and-discovery::category-page", "EXPOSED_VIA"),
    ],
    "customer-registration-and-login": [
        ("WebPresentation", "catalogue-and-discovery::module-page", "EXPOSED_VIA"),
    ],
}

# item_key -> (fields, notes)
DATA_ITEMS: dict[str, tuple[list[str], str]] = {
    "session": (["PrestaShop-adab*"], "Set-Cookie session token; HttpOnly, Secure, SameSite=Lax"),
    "customer_account": (
        ["lql-register-firstname", "lql-register-lastname", "lql-register-email",
         "lql-register-pass", "lql-register-check", "id_gender", "newsletter",
         "lql-email-reset", "lql-rememberme", "lql-pass-login", "lql-email-login"],
        "Customer account record with registration + login credential fields",
    ),
    "shopping_cart": (
        ["id_product", "id_product_attribute", "qty", "quantity_product",
         "minimal_quantity", "id_customization", "token"],
        "The cart's item lines and totals",
    ),
    "newsletter_subscription": (["email", "psgdpr_consent_checkbox"],
                                "Newsletter subscription opt-in"),
    "wishlist_item": (["content"], "A single wishlist item"),
    "wishlist_share": (["wishlist_email_+$i+"], "Wishlist shared to a recipient email"),
    "search_query": (["search_query"], "Catalogue search query"),
}

# service_slug -> [(item_key, direction), ...]  (PRODUCES/CONSUMES)
DATA_FLOWS: dict[str, list[tuple[str, str]]] = {
    "customer-registration-and-login": [
        ("session", "produces"), ("customer_account", "produces"),
        ("newsletter_subscription", "consumes"), ("search_query", "consumes"),
    ],
    "sign-in": [("session", "consumes"), ("customer_account", "consumes")],
    "cart-and-checkout": [("session", "consumes"), ("shopping_cart", "produces"),
                          ("shopping_cart", "consumes")],
    "moodclub-loyalty": [("customer_account", "consumes")],
    "product-page-reviews-wishlist": [
        ("customer_account", "consumes"), ("wishlist_item", "produces"),
        ("wishlist_item", "consumes"), ("wishlist_share", "produces"),
        ("wishlist_share", "consumes"), ("search_query", "consumes"),
    ],
    "catalogue-and-discovery": [("newsletter_subscription", "produces"),
                                ("search_query", "produces")],
}

# (from_item_key, to_item_key, kind, predicate, rationale) - kind from the six
# DATA_RELATIONSHIP_KINDS allowlist (the live ``references`` kind is mapped onto
# the closest allowlist kind SUBSET_OF, per the evidence file's NOTE).
DATA_RELATIONSHIPS: list[tuple[str, str, str, str, str]] = [
    ("shopping_cart", "customer_account", "SUBSET_OF",
     "cart is associated with a customer session",
     "cart is a customer-bound subset of the account's session context"),
    ("wishlist_item", "customer_account", "SUBSET_OF",
     "wishlist item belongs to a customer's wishlist",
     "the wishlist is a per-customer subset projection of the account"),
    ("wishlist_share", "wishlist_item", "SUBSET_OF",
     "share action distributes a wishlist item to a recipient",
     "a share references exactly one wishlist item"),
    ("newsletter_subscription", "customer_account", "SUBSET_OF",
     "subscription is linked to a customer's email preference",
     "the subscription record is derived from the account's email contact"),
]

# (path, method, service_slug) - representative L0 endpoints (subset of the
# recovered ~101).
ENDPOINTS: list[tuple[str, str, str]] = [
    ("/", "GET", "catalogue-and-discovery"),
    ("/it/", "GET", "catalogue-and-discovery"),
    ("/it/login", "GET", "sign-in"),
    ("/it/login", "POST", "sign-in"),
    ("/it/carrello", "GET", "cart-and-checkout"),
    ("/it/module/leofeature/mywishlist", "GET", "product-page-reviews-wishlist"),
    ("/it/moodclub", "GET", "moodclub-loyalty"),
    ("/it/modalita-di-pagamento", "GET", "payments-and-shipping"),
    ("/it/spedizioni-e-resi", "GET", "payments-and-shipping"),
    ("/it/offerte-vini", "GET", "promotional-surfaces"),
    ("/it/outlet-vini", "GET", "promotional-surfaces"),
    ("/it/spumante-brut", "GET", "catalogue-and-discovery"),
    ("/it/barolo", "GET", "catalogue-and-discovery"),
    ("/it/cantine/andreola", "GET", "catalogue-and-discovery"),
    ("/it/cantine/andreola", "POST", "catalogue-and-discovery"),
    ("/it/vini-da-regalare-per-tutte-le-tasche", "POST", "gifting-and-b2b"),
]

BASE = "https://moodique.com"


def load_moodique_l1_fixture(project_id: str, session) -> dict:
    """MERGE the recovered moodique L1 under ``project_id`` (idempotent).

    Seeds the services (with ``service_contract``), the systems (with
    ``exposure`` + ``description``), the typed Service->System edges, the
    L1DataItems with fields/notes, the PRODUCES/CONSUMES flows, the
    DataRelationship edges, and a representative L0 Endpoint surface
    (AGGREGATES from each owning service). Returns the seeded counts.
    """
    service_slugs = list(SERVICES)
    for slug, contract in SERVICES.items():
        session.run(
            "MERGE (:L1TestableUnit:L1Service {business_function_slug: $slug, "
            "project_id: $p, exposure: 'public', service_contract: $contract})",
            slug=slug, p=project_id, contract=contract,
        )
    for kind, (discs, exposure, description) in SYSTEMS.items():
        for disc in discs:
            session.run(
                "MERGE (:L1TestableUnit:L1System {kind: $kind, discriminator: $disc, "
                "project_id: $p, exposure: $exposure, description: $description})",
                kind=kind, disc=disc, p=project_id,
                exposure=exposure, description=description,
            )
    for slug, edges in EDGES.items():
        for kind, disc, rel in edges:
            session.run(
                "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
                "MATCH (sy:L1System {kind: $kind, discriminator: $disc, project_id: $p}) "
                f"MERGE (s)-[:{rel}]->(sy)",
                slug=slug, kind=kind, disc=disc, p=project_id,
            )
    for item_key, (fields, notes) in DATA_ITEMS.items():
        session.run(
            "MERGE (:L1DataItem {item_key: $key, project_id: $p, fields: $fields, "
            "notes: $notes})",
            key=item_key, p=project_id, fields=fields, notes=notes,
        )
    for slug, flows in DATA_FLOWS.items():
        for item_key, direction in flows:
            rel = "PRODUCES" if direction == "produces" else "CONSUMES"
            session.run(
                "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
                "MATCH (d:L1DataItem {item_key: $key, project_id: $p}) "
                f"MERGE (s)-[:{rel}]->(d)",
                slug=slug, key=item_key, p=project_id,
            )
    for from_key, to_key, kind, predicate, rationale in DATA_RELATIONSHIPS:
        session.run(
            "MATCH (a:L1DataItem {item_key: $from_key, project_id: $p}) "
            "MATCH (b:L1DataItem {item_key: $to_key, project_id: $p}) "
            f"MERGE (a)-[:{kind} {{predicate: $predicate, rationale: $rationale}}]->(b)",
            from_key=from_key, to_key=to_key, p=project_id, predicate=predicate,
            rationale=rationale,
        )
    for path, method, slug in ENDPOINTS:
        session.run(
            "MERGE (:Endpoint {path: $path, method: $method, baseurl: $base, "
            "project_id: $p})",
            path=path, method=method, base=BASE, p=project_id,
        )
        session.run(
            "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
            "MATCH (e:Endpoint {path: $path, method: $method, baseurl: $base, "
            "project_id: $p}) "
            "MERGE (s)-[:AGGREGATES {status: 'committed'}]->(e)",
            slug=slug, path=path, method=method, base=BASE, p=project_id,
        )
    return {
        "services": len(SERVICES),
        "systems": sum(len(d) for d, _, _ in SYSTEMS.values()),
        "edges": sum(len(e) for e in EDGES.values()),
        "data_items": len(DATA_ITEMS),
        "data_flows": sum(len(f) for f in DATA_FLOWS.values()),
        "data_relationships": len(DATA_RELATIONSHIPS),
        "endpoints": len(ENDPOINTS),
    }