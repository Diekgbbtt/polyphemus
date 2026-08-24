# PrestaShop (8.2.2)

## Overview

PrestaShop 8.2.2 is an open-source e-commerce platform deployed from the
official Docker image (PHP 8.2 under Apache) with a MySQL 8.0 backend, database
name `prestashop` and table prefix `ps_`. The instance runs as an online
storefront (the classic theme) with the demo "fashion" catalog seeded in -
products, categories, manufacturers and their images - and a separate back
office for shop operators, reached through an admin folder that the runtime
renames to admin-dev. The PrestaShop Checkout payment module (ps_checkout) is
installed on top of the core. The shop is enabled, canonical redirects are
off, friendly URL rewriting is active, and the English translation set is
seeded locally so the store works offline.

## Services

### storefront-home
- contract: Renders the store home page presenting the shop's featured and new products for browsing visitors.
- exposure: public

### category-browsing
- contract: Lists the products of a category with its subcategories and the category's own description and image.
- exposure: public

### product-catalog-listing
- contract: Shows special catalog collections - best-selling products, new products and price drops.
- exposure: public

### product-detail
- contract: Presents a single product page with its name, description, images, price and available product combinations, and the add-to-cart controls.
- exposure: public

### product-search
- contract: Runs a keyword search over the product catalog and shows matching products with facets.
- exposure: public

### manufacturer-browsing
- contract: Lists the shop's manufacturers and the products each brand offers.
- exposure: public

### supplier-browsing
- contract: Lists the shop's suppliers and the products each supplier offers.
- exposure: public

### cms-content
- contract: Renders the shop's CMS pages and CMS page categories, e.g. the terms, about and delivery-information pages.
- exposure: public

### sitemap
- contract: Publishes the site map of pages, categories and products of the store.
- exposure: public

### store-locator
- contract: Shows the shop's physical stores with their addresses and opening information.
- exposure: public

### contact-form
- contract: Accepts visitor messages submitted through the contact page with name, email and subject, and forwards them to the shop's customer service.
- exposure: public

### shopping-cart
- contract: Manages the visitor's cart - adding, removing and updating product quantities - and displays the running total.
- exposure: public

### checkout
- contract: Walks the customer through the multi-step order process: delivery and invoice addresses, delivery options and the payment step, then places the order.
- exposure: public

### checkout-payment
- contract: Presents the payment step of checkout through the PrestaShop Checkout module, which creates a payment order for the current cart, lets the customer complete it and confirms the outcome on return and through callback notifications.
- exposure: public

### order-confirmation
- contract: Confirms a completed order to the customer and shows its reference, summary and any payment instructions.
- exposure: public

### customer-login
- contract: Authenticates a registered customer by email and password and opens the customer session.
- exposure: public

### customer-registration
- contract: Creates a new customer account from the registration form's personal and address details.
- exposure: public

### customer-account-overview
- contract: Shows the logged-in customer a summary of their account with links to orders, addresses and personal data.
- exposure: authenticated

### customer-profile-management
- contract: Lets the customer update their personal information and change their password.
- exposure: authenticated

### customer-address-management
- contract: Lists the customer's delivery and invoice addresses and lets them add, edit and delete addresses.
- exposure: authenticated

### customer-order-history
- contract: Lists the orders the customer has placed with their statuses.
- exposure: authenticated

### customer-order-detail
- contract: Shows the items, addresses and status of a single customer order, including reorder and delivery-file actions.
- exposure: authenticated

### order-follow
- contract: Tracks the delivery and return status of the customer's orders.
- exposure: authenticated

### order-return
- contract: Lets the customer request a return for items of an order.
- exposure: authenticated

### order-slip
- contract: Shows the credit slips issued against the customer's orders.
- exposure: authenticated

### guest-order-tracking
- contract: Lets an unregistered visitor check the status of an order using its reference and billing email.
- exposure: public

### password-recovery
- contract: Emails a password reset link to a registered customer so they can choose a new password.
- exposure: public

### downloadable-product-delivery
- contract: Serves the files customers are entitled to download from their orders - digital product files and order attachments.
- exposure: authenticated

### pdf-document-delivery
- contract: Generates and serves PDF documents for orders: the invoice, the order return and the order slip.
- exposure: authenticated

### customer-file-upload
- contract: Accepts files uploaded by the customer in the context of an order, for example with a return request.
- exposure: authenticated

### currency-switching
- contract: Switches the storefront price display between the shop's enabled currencies.
- exposure: public

### storefront-statistics-tracking
- contract: Reports storefront view statistics back to the shop through a small tracking request.
- exposure: public

### back-office-authentication
- contract: Presents the back-office login screen, verifies employee email and password, opens the employee session and signs the employee out on logout; also supports password recovery for employees.
- exposure: public

### back-office-dashboard
- contract: Shows the back-office landing dashboard with an overview of the shop's recent orders, customers and activity.
- exposure: authenticated

### product-administration
- contract: Manages the product catalog from the back office: lists and filters products, creates and edits products with their descriptions, prices, images, combinations, features and specific prices, and manages virtual products and attachments. Includes an autocomplete that looks up products by name or reference while editing.
- exposure: authenticated

### category-administration
- contract: Manages the category tree - creating, editing, moving and deleting categories and assigning products.
- exposure: authenticated

### order-administration
- contract: Manages customer orders from the back office: lists and views orders, edits their details and statuses, and manages carts, invoices, delivery slips and credit slips.
- exposure: authenticated

### customer-administration
- contract: Manages customer accounts - listing, creating, editing and deleting customers and viewing their orders and addresses.
- exposure: authenticated

### data-import
- contract: Imports catalog and shop data from uploaded CSV files - products, categories, combinations, customers, suppliers - with a field-matching step, and copies product and category images referenced by URLs in the import data, saving them into the shop's image storage.
- exposure: authenticated

### sql-query-manager
- contract: Lets an operator write, save and run SQL queries against the shop database and view or export the results.
- exposure: authenticated

### webservice-key-management
- contract: Manages the API keys and permission scopes for the shop's web service interface.
- exposure: authenticated

### module-management
- contract: Lists installed modules and their versions, and installs, uninstalls, enables, disables, resets, upgrades and configures modules from the back office.
- exposure: authenticated

### employee-management
- contract: Manages the back-office employee accounts - listing, creating, editing, enabling and disabling employees and their passwords.
- exposure: authenticated

### profile-and-permission-management
- contract: Manages the employee profiles that group permissions, and assigns per-controller access rights (view, add, edit, delete) to each profile.
- exposure: authenticated

### shop-configuration
- contract: Configures general shop settings: the store's identity, products, customers, orders, maintenance, performance, multistore shops and shop URLs.
- exposure: authenticated

### design-and-theme
- contract: Manages the storefront appearance: selects and configures the theme, uploads logos, edits layout positions, CMS pages and mail themes.
- exposure: authenticated

### internationalization
- contract: Manages the shop's locales: languages, currencies, countries, states, zones, taxes and tax rules, translations and geolocation settings.
- exposure: authenticated

### payment-administration
- contract: Manages the payment methods enabled in the shop and their preferences, including which currencies and countries each method accepts.
- exposure: authenticated

### carrier-administration
- contract: Manages the shipping carriers - their names, delays, prices, ranges, zones and handling preferences.
- exposure: authenticated

### customer-service-administration
- contract: Manages the customer service threads and the messages customers and operators exchange through the contact and order flows.
- exposure: authenticated

### discount-management
- contract: Creates and manages cart rules (vouchers and promotions) and catalog price rules that apply conditional discounts to carts and products.
- exposure: authenticated

### stock-and-warehouse-management
- contract: Shows the current stock levels and stock movements of products and manages the warehouses products are stored in.
- exposure: authenticated

### statistics-and-reports
- contract: Shows the back-office statistics and report pages about the shop's sales, customers and traffic.
- exposure: authenticated

### audit-log-access
- contract: Reviews the recorded administration logs and email log entries, configures logging and clears logged entries.
- exposure: authenticated

### database-backup
- contract: Creates, downloads, deletes and restores database backups of the shop.
- exposure: authenticated

### email-configuration
- contract: Configures the shop's email sending transport, SMTP server and email templates, and sends test emails.
- exposure: authenticated

### attribute-and-feature-management
- contract: Manages the product attributes, attribute groups, features and feature values that products use for combinations and classification.
- exposure: authenticated

### attachment-management
- contract: Manages the attachments that can be added to products for download.
- exposure: authenticated

### manufacturer-administration
- contract: Manages the manufacturers of the shop with their logos and addresses.
- exposure: authenticated

### supplier-administration
- contract: Manages the suppliers of the shop with their logos and addresses.
- exposure: authenticated

### product-monitoring
- contract: Lists the products needing attention - out of stock, products without price, and disabled products.
- exposure: authenticated

### back-office-search
- contract: Runs a search across back-office records and content and manages the search configuration and search aliases.
- exposure: authenticated

### image-type-management
- contract: Manages the image sizes (image types) the storefront uses for product, category, manufacturer and supplier images, and regenerates them.
- exposure: authenticated

### order-status-management
- contract: Manages the order statuses the shop assigns to orders and their mail template and invoice behavior.
- exposure: authenticated

### customer-group-management
- contract: Manages the customer groups that classify customers and gate price visibility and discounts.
- exposure: authenticated

### tag-management
- contract: Manages the product tags used in product search.
- exposure: authenticated

### gender-management
- contract: Manages the customer gender options offered during registration.
- exposure: authenticated

## Systems

### authentication - cookie session mechanism
- description: PrestaShop's encrypted-cookie sessions (cookie key and IV from the application parameters) authenticate the front-office customer and the back-office employee; the employee session is additionally guarded by an admin CSRF token in requests.

### authorization - permission mechanism
- description: Back-office access is granted per controller by employee profile and per-action rights (view, add, edit, delete); the front office distinguishes guest, customer and employee contexts.

### persistence - database mechanism
- description: MySQL 8.0 database named `prestashop`, InnoDB, utf8mb4, with the `ps_` table prefix; holds products, categories, orders, customers, employees, configuration and the module tables.
- description: the seeded database also contains the shop URL and domain configuration records that drive generated links.

### routing - web routing mechanism
- description: Apache with mod_rewrite and PrestaShop's dispatcher map friendly URLs (product, category, supplier, manufacturer, CMS, module and upload) and the legacy query-controller endpoints; the runtime regenerates the rewrite rules and prefers the request host when building links.

### rendering - template mechanism
- description: The storefront renders through Smarty templates of the classic theme; the back office renders through Symfony Twig templates with legacy Smarty admin controllers.

### storage - media file mechanism
- description: Product, category, manufacturer and supplier images live in the application's image directories in numeric-id subpaths; uploads and translations also reside on the application's local disk.

### processing - image mechanism
- description: Images are resized into the configured image types, and the import service copies product and category images from URLs in the import data, checking the supplied value against a list of refused hostnames and fetching the decoded value into the image storage.

### notification - mail mechanism
- description: Transactional mail (order confirmation, password recovery, customer messages) is dispatched through the configured SMTP transport with mail templates; the deployed transport points at the loopback address.

### integration - payment provider mechanism
- description: The ps_checkout module integrates the store's checkout with an external payment provider; it exposes its own front controllers that create a payment order, finalize payment and receive callback notifications.

### internationalization - translation mechanism
- description: Multilingual content keys are served from the translation set seeded locally (English) and the theme's language files; modules use the same translation pipeline.

### caching - cache mechanism
- description: A memcache-style cache driver is configured but disabled in the deployed parameters; the runtime clears the compiled cache directories on startup.

## Roles

- guest: anonymous storefront visitor who can browse the catalog, search and add to cart, and track an order with its reference.
- customer: registered front-office account holder, session-authenticated, with access to orders, addresses, profile and downloads.
- employee: back-office operator, session-authenticated and authorized per controller by the permissions of their profile.
- superadmin: the default employee profile holding every back-office permission, able to manage the shop and its configuration.

## Service-system mapping

- storefront-home, category-browsing, product-catalog-listing, product-detail, product-search, manufacturer-browsing, supplier-browsing, cms-content, sitemap, store-locator rely on the routing, template and database mechanisms.
- contact-form relies on the routing and template mechanisms for the form and the mail mechanism for forwarding.
- shopping-cart, checkout, order-confirmation rely on the routing and template mechanisms, the database mechanism for the cart and order records and the cookie session mechanism for the cart owner.
- checkout-payment relies on the checkout flow plus the payment provider mechanism and the cookie session mechanism.
- customer-login, customer-registration rely on the cookie session and database mechanisms.
- customer-account-overview, customer-profile-management, customer-address-management, customer-order-history, customer-order-detail, order-follow, order-return, order-slip, downloadable-product-delivery, pdf-document-delivery, customer-file-upload rely on the cookie session, routing, template and database mechanisms and the media file mechanism.
- guest-order-tracking relies on the routing, template and database mechanisms.
- password-recovery relies on the routing and template mechanisms for the request and the mail mechanism for the reset link.
- currency-switching and storefront-statistics-tracking rely on the routing and template mechanisms and the database mechanism.
- back-office-authentication relies on the cookie session mechanism and the authorization mechanism.
- back-office-dashboard and the back-office management services (product-administration, category-administration, order-administration, customer-administration, data-import, sql-query-manager, webservice-key-management, module-management, employee-management, profile-and-permission-management, shop-configuration, design-and-theme, internationalization, payment-administration, carrier-administration, customer-service-administration, discount-management, stock-and-warehouse-management, statistics-and-reports, audit-log-access, database-backup, email-configuration, attribute-and-feature-management, attachment-management, manufacturer-administration, supplier-administration, product-monitoring, back-office-search, image-type-management, order-status-management, customer-group-management, tag-management, gender-management) rely on the cookie session mechanism for the employee session, the authorization mechanism for profile permissions, the routing and template mechanisms for their screens, and the database mechanism for persistence.
- data-import relies on the media file mechanism and the image mechanism to copy images referenced by the import data.
- database-backup relies on the database mechanism to produce backup files.
- email-configuration and the mail-dependent services rely on the mail mechanism.
- sql-query-manager and statistics-and-reports rely on the database mechanism.
- audit-log-access relies on the database mechanism for log persistence.
- design-and-theme and image-type-management rely on the media file mechanism and the image mechanism.
- webservice-key-management manages access to the web service interface that is exposed by the routing mechanism when enabled.