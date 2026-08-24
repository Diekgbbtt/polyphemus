# PrestaShop (8.2.2) - reverse-engineered endpoint inventory

Source: pinned upstream PrestaShop 8.2.2 (controllers, routing configs, the
PrestaShop Checkout module controllers) + the deployed checkout artifacts
(Dockerfile, patches, compose, init scripts). Host is the internal
`http://prestashop:80`; the back office is served from the admin folder the
runtime renames to admin-dev. All paths are relative to the site root.

Route notes:
- Friendly URLs are active (the init script regenerates the rewrite rules).
  Each front controller is also reachable through the legacy query form
  `index.php?controller=<name>`.
- Front-office session cookie: `PrestaShop-<hash>`; back-office cookie
  `PrestaShop-<hash>` on the admin host; both encrypted with the app's cookie
  key/IV.
- Back-office requests require an admin CSRF `token` (per employee) on legacy
  admin query routes and the Symfony admin session.

## Storefront - catalog

### storefront-home
- method: GET
- path: `/`
- params: none (front controller index)
- shape: full HTML page of the home template (featured products, category tree).
- role: guest / customer

### category-browsing
- method: GET
- path: `/{id}-{rewrite}` (e.g. `/3-men`) or `index.php?controller=category&id_category={id}`
- params: `id_category` (numeric), `rewrite` (slug); pagination via `page`
- shape: HTML product grid for the category plus subcategories.
- role: guest / customer

### product-catalog-listing
- method: GET
- path: `index.php?controller=best-sales`, `index.php?controller=new-products`, `index.php?controller=prices-drop`
- params: pagination via `page`
- shape: HTML product grid of the respective collection.
- role: guest / customer

### product-detail
- method: GET / POST
- path: `/{category:/}{id}{-:id_product_attribute}-{rewrite}{-:ean13}.html` or `index.php?controller=product&id_product={id}`
- params: `id_product`, optional `id_product_attribute` (combination), `rewrite`; POST adds the selected combination to cart.
- shape: HTML product page; POST add-to-cart responds with cart refresh.
- role: guest / customer

### product-search
- method: GET
- path: `index.php?controller=search&s={keyword}`
- params: `s` (search query), optional facets (`q`, categories)
- shape: HTML search results page.
- role: guest / customer

### manufacturer-browsing
- method: GET
- path: `/brand/{id}-{rewrite}` or `index.php?controller=manufacturer&id_manufacturer={id}`
- params: `id_manufacturer`, `rewrite`; pagination via `page`
- shape: HTML page of the brand and its products.
- role: guest / customer

### supplier-browsing
- method: GET
- path: `/supplier/{id}-{rewrite}` or `index.php?controller=supplier&id_supplier={id}`
- params: `id_supplier`, `rewrite`; pagination via `page`
- shape: HTML page of the supplier and its products.
- role: guest / customer

### cms-content
- method: GET
- path: `/content/{id}-{rewrite}` or `index.php?controller=cms&id_cms={id}`; categories `/content/category/{id}-{rewrite}` or `index.php?controller=cms&id_cms_category={id}`
- params: `id_cms` / `id_cms_category`, `rewrite`
- shape: HTML CMS page.
- role: guest / customer

### sitemap
- method: GET
- path: `index.php?controller=sitemap`
- shape: HTML sitemap of pages, categories and products.
- role: guest / customer

### store-locator
- method: GET
- path: `index.php?controller=stores`
- shape: HTML page of shop locations.
- role: guest / customer

### contact-form
- method: GET / POST
- path: `index.php?controller=contact`
- params (POST): `from` (email), `message`, `subject`, `id_contact`, captcha/`g-recaptcha-response` if enabled
- shape: HTML form; POST submits the message and confirms.
- role: guest / customer

## Storefront - cart and checkout

### shopping-cart
- method: GET / POST
- path: `index.php?controller=cart`; ajax actions `index.php?controller=cart&ajax=1&action=update|refresh|productRefresh` (POST)
- params: `add`, `delete`, `id_product`, `qty`; `token` (cart token when token check enabled)
- shape: HTML cart page; ajax responses are JSON/HTML fragments with cart totals.
- role: guest / customer

### checkout
- method: GET / POST
- path: `index.php?controller=order`; ajax `index.php?controller=order&ajax=1&action=selectDeliveryOption|addressForm|checkCartStillOrderable`
- params: `id_address_delivery`, `id_address_invoice`, `delivery_option`, `message`, `payment_method`
- shape: multi-step HTML checkout; ajax returns delivery/address options and availability.
- role: guest / customer

### checkout-payment (ps_checkout module)
- method: POST (ajax) / GET
- path: `/module/ps_checkout/create`, `/module/ps_checkout/validate`, `/module/ps_checkout/payment`, `/module/ps_checkout/check`, `/module/ps_checkout/cancel`, `/module/ps_checkout/vault`, `/module/ps_checkout/ExpressCheckout`, `/module/ps_checkout/applepay`, `/module/ps_checkout/googlepay`, `/module/ps_checkout/webhook`, `/module/ps_checkout/DispatchWebHook`; fallback `index.php?fc=module&module=ps_checkout&controller=<name>`
- params: JSON cart/payment data on create; payment token and payer data on validate/payment; provider callback payloads on webhook endpoints
- shape: JSON responses carrying the payment order reference and confirmation state; webhooks receive provider notifications and acknowledge them.
- role: guest / customer (webhook callbacks are unauthenticated provider notifications)

### order-confirmation
- method: GET
- path: `index.php?controller=order-confirmation&id_cart={id}&id_module={id}&id_order={id}&key={order_key}`
- params: `id_cart`, `id_module`, `id_order`, `key` (order reference key)
- shape: HTML confirmation page with order reference and totals.
- role: guest / customer

## Storefront - customer account

### customer-login
- method: GET / POST
- path: `index.php?controller=authentication`
- params (POST): `email`, `passwd`, `back` (redirect), `SubmitLogin`
- shape: HTML login form; POST opens the customer session and redirects.
- role: guest

### customer-registration
- method: GET / POST
- path: `index.php?controller=registration`
- params (POST): `customer_firstname`, `customer_lastname`, `email`, `passwd`, address fields, `submitCreate`
- shape: HTML registration form; POST creates the account and logs in.
- role: guest

### customer-account-overview
- method: GET
- path: `index.php?controller=my-account`
- shape: HTML account dashboard.
- role: customer

### customer-profile-management
- method: GET / POST
- path: `index.php?controller=identity`
- params (POST): personal data fields, `old_passwd`, `passwd`, `submitIdentity`
- shape: HTML form; POST updates the profile and password.
- role: customer

### customer-address-management
- method: GET / POST
- path: `index.php?controller=addresses` (list), `index.php?controller=address` (form), `index.php?controller=address&id_address={id}&delete=1` (delete)
- params: `id_address`, address fields (`firstname`, `lastname`, `address1`, `city`, `postcode`, `id_country`, ...), `submitAddress`
- shape: HTML address book; POST creates/updates the address.
- role: customer

### customer-order-history
- method: GET
- path: `index.php?controller=history`
- shape: HTML list of the customer's orders.
- role: customer

### customer-order-detail
- method: GET
- path: `index.php?controller=order-detail&id_order={id}`
- params: `id_order`
- shape: HTML order detail page; POST reorder actions.
- role: customer

### order-follow
- method: GET
- path: `index.php?controller=order-follow`
- shape: HTML tracking of the customer's orders.
- role: customer

### order-return
- method: GET / POST
- path: `index.php?controller=order-return` (list), `index.php?controller=order-return&id_order_return={id}` (detail), `index.php?controller=order-return&id_order={id}` (request)
- params: `id_order`, `id_order_return`, product quantities, `submitReturn`
- shape: HTML return request form and return status.
- role: customer

### order-slip
- method: GET
- path: `index.php?controller=order-slip`
- shape: HTML list of the customer's credit slips.
- role: customer

### guest-order-tracking
- method: GET / POST
- path: `index.php?controller=guest-tracking`
- params: `order_reference`, `email` (POST tracking query)
- shape: HTML order status page for a guest.
- role: guest

### password-recovery
- method: GET / POST
- path: `index.php?controller=password-recovery`
- params: `email` (request reset)
- shape: HTML form; POST sends a reset email / shows the reset token step.
- role: guest

### downloadable-product-delivery
- method: GET
- path: `index.php?controller=attachment&id_attachment={id}`; digital files via `index.php?controller=getfile&key={key}&id_order={id}&id_product={id}`; also `index.php?controller=download`
- params: `id_attachment`, `key`, `id_order`, `id_product`
- shape: binary file download stream (attachment headers).
- role: customer

### pdf-document-delivery
- method: GET
- path: `index.php?controller=pdf-invoice&id_order={id}`, `index.php?controller=pdf-order-return&id_order_return={id}`, `index.php?controller=pdf-order-slip&id_order_slip={id}`
- params: `id_order`, `id_order_return`, `id_order_slip`
- shape: application/pdf document download.
- role: customer

### customer-file-upload
- method: POST
- path: `index.php?controller=upload` (inherits from the file-delivery controller)
- params: uploaded file, order context (`id_order`, `id_order_detail`)
- shape: HTML fragment confirming the stored upload; binary data is accepted as a file upload.
- role: customer

### currency-switching
- method: GET
- path: `index.php?controller=change-currency&id_currency={id}`
- params: `id_currency`
- shape: redirect back to the referrer with the new currency in session.
- role: guest / customer

### storefront-statistics-tracking
- method: GET
- path: `index.php?controller=statistics&token={hash}`
- params: `token` (merchant stats token), `n`, `p`, `date` (view counters)
- shape: image/gif response recording a view.
- role: guest / customer

## Storefront - module and file routes

### module front controllers
- method: GET / POST
- path: `/module/{module}/{controller}` or `index.php?fc=module&module={module}&controller={controller}`
- params: per module; ps_checkout endpoints as listed under checkout-payment; other enabled modules (shopping cart, search, contact info, main menu, featured products, language/currency selector, customer account links, etc.) expose their own ajax/display controllers.
- shape: module-rendered HTML/JSON.
- role: guest / customer, per module

### file delivery (generic)
- method: GET
- path: `/upload/{file}` (friendly) or `index.php?controller=upload`
- params: `file` path component
- shape: file download for order-attached uploads.
- role: guest (per file key) / customer

## Back office (admin-dev)

The back office lives under the admin-dev folder (renamed from `admin` at
startup). Legacy entry is `index.php` inside that folder with
`controller=<AdminController>` plus the per-employee `token`. Symfony routes
are mounted below the same folder. All back-office screens require an
authenticated employee session and profile permission for the controller.

### back-office-authentication
- method: GET / POST
- path: `admin-dev/` and `admin-dev/index.php?controller=AdminLogin`
- params (POST): `email`, `passwd`, `redirect`, `submitLogin`; logout via `index.php?controller=AdminLogin&logout=1`
- shape: HTML login page; POST sets the employee cookie and redirects; reset-password flow via email.
- role: guest (login screen) -> employee

### back-office-dashboard
- method: GET
- path: `admin-dev/` (Symfony), legacy `admin-dev/index.php?controller=AdminDashboard`
- params: none; notifications via ajax `admin-dev/notifications` (POST)
- shape: HTML dashboard with counters and recent orders/customers.
- role: employee

### product-administration
- method: GET / POST / ajax
- path: legacy `admin-dev/index.php?controller=AdminProducts`; Symfony `admin-dev/` product catalog (`admin_product_catalog`, `admin_product_form`, `admin_product_new`, combination/attribute/feature/specific-price/warehouse sub-resources)
- params: `id_product`, `token`; list filters (`submitFilterproduct`); ajax `action=productsList`, `action=productPackItems`, `action=productManufacturers`, `action=addProductImage`, `action=publishProduct`, `action=updatePositions`, `action=productQuantity`, `action=checkProductName`; form POSTs `submitAddproduct` etc.
- shape: HTML catalog list and product form; ajax returns product lookup results (name/reference matching as newline-delimited `name|id` pairs or JSON) and image/save results.
- role: employee (product profile)

### category-administration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminCategories`; Symfony `admin_categories_index` (list/create/edit/move/delete, `/{categoryId}`, `/new`, `/{categoryId}/edit`, `/delete`, `/bulk-delete`)
- params: `id_category`, `token`, category fields, `submitAddcategory`
- shape: HTML category tree and form; POST saves/deletes.
- role: employee (category profile)

### order-administration
- method: GET / POST / ajax
- path: legacy `admin-dev/index.php?controller=AdminOrders`; Symfony `admin_orders_index` (list/view/edit), `admin_orders_*` (invoices, delivery slips, credit slips `admin_credit_slips_*`, carts `admin_carts_*`)
- params: `id_order`, `token`, `submitFilterOrder`, order edits (`submitState`, `submitMessage`); PDF generation routes per order
- shape: HTML order list/detail; PDF responses for invoice/delivery-slip documents.
- role: employee (order profile)

### customer-administration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminCustomers`; Symfony `admin_customers_index` (`/new`, `/{customerId}/edit`, `/{customerId}/view`, `/{customerId}/set-private-note`, `/delete`)
- params: `id_customer`, `token`, customer fields, `submitAddcustomer`
- shape: HTML customer list and form.
- role: employee (customer profile)

### data-import
- method: GET / POST / ajax
- path: legacy `admin-dev/index.php?controller=AdminImport`; Symfony `admin_import` (`/`, `/file/upload`, `/file/delete`, `/file/download`, `/sample/download/{sampleName}`, `/process`, `/data`, `/match`, `/fields`)
- params: `token`, uploaded CSV file, entity type, field matching, import options; the process step reads CSV rows and for product/category rows whose image field holds a URL, copies the remote image into the shop image storage
- shape: HTML import wizard; `/file/upload` accepts a CSV upload and returns the stored file id; `/process` executes the import and reports row counts; `/fields` returns available entity fields as JSON.
- role: employee (import profile)

### sql-query-manager
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminRequestSql`; Symfony `admin_sql_requests_index` (`/new`, `/{sqlRequestId}/edit`, `/{sqlRequestId}/delete`, `/process-settings`)
- params: `token`, `sql` (query text), `submitAddrequest_sql`
- shape: HTML query editor; POST runs the query and shows/export the result grid.
- role: employee (SQL manager profile)

### webservice-key-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminWebservice`; Symfony `admin_webservice_keys_index` (`/new`, `/{webserviceKeyId}/edit`, `/{webserviceKeyId}/delete`, `/settings`)
- params: `token`, key fields, resource permissions
- shape: HTML key list and form.
- role: employee (webservice profile)

### module-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminModules`; Symfony `admin_module_manage` (`/manage/{category}/{keyword}`, `/manage/action/{action}/{module_name}`, `/manage/bulk/{action}`, `/import`)
- params: `token`, module name, action (`install|uninstall|enable|disable|reset|upgrade|delete`), `configure`
- shape: HTML module catalog; POST actions toggle module state; configure loads the module's config screen.
- role: employee (module profile)

### employee-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminEmployees`; Symfony `admin_employees_index` (`/new`, `/{employeeId}/edit`, `/toggle-status`, `/save-options`)
- params: `token`, employee fields, `id_profile`, `passwd`
- shape: HTML employee list and form.
- role: employee (employee profile)

### profile-and-permission-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminProfiles`, `AdminAccess`; Symfony `admin_profiles_*`, `admin_permissions_*`
- params: `token`, profile name, per-controller permission toggles (view/add/edit/delete)
- shape: HTML profile list and permission matrix.
- role: employee (profile/permission rights)

### shop-configuration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminPreferences`, `AdminPerformance`, `AdminAdministration`, `AdminShop`, `AdminShopGroup`, `AdminShopUrl`; Symfony `admin_preferences`, `admin_performance`, `admin_administration`, `admin_shops_*`, `admin_shop_urls_*`, `admin_shop_groups_*`, `admin_feature_flags`
- params: `token`, configuration field POSTs (`submitOptions...`)
- shape: HTML configuration forms; POST saves settings.
- role: employee (preferences/performance/shop rights)

### design-and-theme
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminThemes`, `AdminModulesPositions`; Symfony `admin_themes_index` (`/upload-logos`, `/export`, `/import`), `admin_theme_catalog`, `admin_positions_*`, `admin_cms_pages_*`, `admin_mail_theme_*`
- params: `token`, theme selection, logo uploads, position moves, CMS page fields
- shape: HTML theme/config screens.
- role: employee (theme/design rights)

### internationalization
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminLocalization`, `AdminLanguages`, `AdminCurrencies`, `AdminCountries`, `AdminStates`, `AdminZones`, `AdminTaxes`, `AdminTaxRulesGroup`, `AdminTranslations`, `AdminGeolocation`; Symfony `admin_localization_*`, `admin_languages_*`, `admin_currencies_*`, `admin_countries_*`, `admin_states_*`, `admin_zones_*`, `admin_taxes_*`, `admin_tax_rules_groups_*`, `admin_international_translations_*`, `admin_geolocation_*`
- params: `token`, per-feature fields (`submitOptions...`, add/edit/delete)
- shape: HTML configuration forms and CRUD screens.
- role: employee (international rights)

### payment-administration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminPayment`, `AdminPaymentPreferences`; Symfony `admin_payment_methods_*`, `admin_payment_preferences`
- params: `token`, payment module activation, per-currency/per-country preferences
- shape: HTML payment configuration screens.
- role: employee (payment rights)

### carrier-administration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminCarriers`, `AdminCarrierWizard`; Symfony `admin_carriers_*`, `admin_shipping_preferences`
- params: `token`, carrier fields, price ranges, zones, handling charges
- shape: HTML carrier list/wizard and shipping preferences.
- role: employee (carrier rights)

### customer-service-administration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminCustomerThreads`; Symfony `admin_customer_threads` (`/`, `/{customerThreadId}/view`, `/{customerThreadId}/reply`, `/{customerThreadId}/update-status`)
- params: `token`, `id_customer_thread`, message text
- shape: HTML thread list and message view/reply.
- role: employee (customer service rights)

### discount-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminCartRules`, `AdminSpecificPriceRule`, `AdminSpecificPrice`; Symfony `admin_cart_rules_*`, `admin_catalog_price_rules_*`, product `specific-prices` sub-resources
- params: `token`, rule fields, conditions, `submitAddcart_rule` etc.
- shape: HTML rule list and form.
- role: employee (cart-rule / price-rule rights)

### stock-and-warehouse-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminStocks`; Symfony `admin_stock_overview`, `admin_stock_movements_overview`, `admin_warehouses_*`
- params: `token`, stock updates, movement filters, warehouse fields
- shape: HTML stock overview with quantity updates and movement log.
- role: employee (stock rights)

### statistics-and-reports
- method: GET
- path: legacy `admin-dev/index.php?controller=AdminStats`, `AdminStatsTab`; Symfony `admin_statistics`
- params: `token`, module-based stat tabs
- shape: HTML statistics dashboards.
- role: employee (statistics rights)

### audit-log-access
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminLogs`; Symfony `admin_logs_index` (`/settings`, `/delete-all`)
- params: `token`, log filters
- shape: HTML log list; POST clears entries.
- role: employee (logs rights)

### database-backup
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminBackup`; Symfony `admin_backups_index` (`/new`, `/download/{file}`, `/view/{file}`, `/delete/{file}`)
- params: `token`, backup file name
- shape: HTML backup list; POST creates a backup; downloads serve the .sql backup file.
- role: employee (backup rights)

### email-configuration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminEmails`; Symfony `admin_emails_index` (`/options`, `/send-testing-email`)
- params: `token`, mail transport fields, `PS_MAIL_METHOD`, test recipient
- shape: HTML mail config form and test-send.
- role: employee (email rights)

### attribute-and-feature-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminAttributesGroups`, `AdminFeatures`, `AdminAttributes`; Symfony `admin_attributes_*`, `admin_attribute_groups_*`, `admin_features_*` (+ product combination sub-resources)
- params: `token`, attribute/group/feature/value fields
- shape: HTML CRUD screens for attributes, groups, features and values.
- role: employee (attribute/feature rights)

### attachment-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminAttachments`; Symfony `admin_attachments_*`
- params: `token`, attachment file fields
- shape: HTML attachment list/form.
- role: employee (attachment rights)

### manufacturer-administration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminManufacturers`; Symfony `admin_manufacturers_*`
- params: `token`, manufacturer fields, logo upload
- shape: HTML manufacturer list/form.
- role: employee (manufacturer rights)

### supplier-administration
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminSuppliers`; Symfony `admin_suppliers_*`
- params: `token`, supplier fields, logo upload
- shape: HTML supplier list/form.
- role: employee (supplier rights)

### product-monitoring
- method: GET
- path: legacy `admin-dev/index.php?controller=AdminMonitoring`; Symfony `admin_monitoring_*`
- params: `token`
- shape: HTML lists of products needing attention.
- role: employee (monitoring rights)

### back-office-search
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminSearch`, `AdminSearchConf`; Symfony `admin_search_*`, `admin_search_conf_*`
- params: `token`, `bo_query` (global search), search index config
- shape: HTML back-office search results and search configuration.
- role: employee (search rights)

### image-type-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminImages`; Symfony `admin_image_settings_*`
- params: `token`, image type width/height fields, regenerate actions
- shape: HTML image type list/form; POST regenerates images.
- role: employee (images rights)

### order-status-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminStatuses`; Symfony `admin_order_statuses_*`
- params: `token`, status fields, mail template toggle
- shape: HTML order status list/form.
- role: employee (order-status rights)

### customer-group-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminGroups`; Symfony `admin_groups_*`
- params: `token`, group fields, price display settings
- shape: HTML customer group list/form.
- role: employee (groups rights)

### tag-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminTags`
- params: `token`, tag fields
- shape: HTML tag list/form.
- role: employee (tags rights)

### gender-management
- method: GET / POST
- path: legacy `admin-dev/index.php?controller=AdminGenders`
- params: `token`, gender fields
- shape: HTML gender list/form.
- role: employee (genders rights)

## Web service

### webservice REST API
- method: GET / POST / PUT / DELETE
- path: `webservice/dispatcher.php` (or `api/...`) with resource in the query/path (e.g. `webservice/dispatcher.php?resource=products`), authenticated by API key
- params: `resource`, `id` (e.g. `?resource=customers&id=1`), `output_format` (JSON/XML), `ws_key` or Authorization header
- shape: JSON/XML representations of PrestaShop resources (products, customers, orders, addresses, ...).
- role: webservice API key (managed via webservice-key-management), when the web service is enabled
- note: availability depends on the `PS_WEBSERVICE` configuration and the presence of a valid API key; the deployed seed state of this toggle was not observable from the checkout artifacts.