# SkiFlux Backend API

This is the backend API for the SkiFlux platform, built with Django, Django REST Framework, and Celery. It follows a clean service-repository architecture to keep business logic, persistence, and API presentation separate.

## 🏛️ Architecture Overview

The project is organized into these core layers:
* **Views (`skiflux/views/`)**: HTTP endpoints, request validation, and response assembly.
* **Serializers (`skiflux/serializers/`)**: Input validation and API response object shaping.
* **Services (`skiflux/services/`)**: Business workflows, including payments, wallets, withdrawals, content approval, and admin operations.
* **Repositories (`skiflux/repositories/`)**: Database access abstractions for models.
* **Models (`skiflux/models/`)**: Django ORM entities representing core domain objects.
* **Tasks (`skiflux/tasks/`)**: Celery-powered asynchronous jobs.

## 🛠️ Prerequisites

Install the following before running the project:
* **Python 3.12+**
* **Poetry**
* **PostgreSQL** (recommended for production-like development)
* **Redis** (required for Celery and cache)

## 🚀 Local Setup

### 1. Install dependencies

```bash
cd skiflux_project
poetry install
```

If you need developer tooling such as Ruff and formatting checks:

```bash
poetry install --with dev
```

### 2. Configure environment variables

Copy the environment template and update values:

```bash
cp env-example .env
```

Required core variables:
* `DATABASE_URL`
* `REDIS_URL`
* `SECRET_KEY`
* `USER_JWT_SECRET`
* `ADMIN_JWT_SECRET`
* `PAYLOAD_ENCRYPTION_KEY`
* `PUBLIC_API_BASE_URL`
* `EMAIL_HOST_USER`
* `EMAIL_HOST_PASSWORD`

Required payment variables:
* `FLUTTERWAVE_SECRET_KEY`
* `FLUTTERWAVE_WEBHOOK_SECRET`
* `PAYSTACK_SECRET_KEY`
* `PAYSTACK_PUBLIC_KEY`
* `STRIPE_SECRET_KEY`
* `STRIPE_PUBLISHABLE_KEY`
* `STRIPE_WEBHOOK_SECRET`
* `ADYEN_API_KEY`
* `ADYEN_MERCHANT_ACCOUNT`
* `ADYEN_ENVIRONMENT`
* `ADYEN_WEBHOOK_SECRET`
* `PAYMENT_REDIRECT_URL`

> Security note: never commit real secret keys or production credentials to source control.

### 3. Database setup

Apply database migrations:

```bash
poetry run python manage.py migrate
```

Optionally create a superuser for admin operations:

```bash
poetry run python manage.py createsuperuser
```

Create an internal superadmin with all privileges for admin operations and more:

```bash
poetry run python manage.py createsuperadmin
```

## 🧹 Code Quality / Linting

This project uses Ruff for lint checking and auto-fixing Python code.

Run lint checks only:
```bash
poetry run ruff check .
```

Run fixes only:
```bash
poetry run ruff check --fix .
```

Run a format, check and then fix issues in sequence:
```bash
poetry run ruff format . && poetry run ruff check --fix .
```

> Tip: `poetry run ruff check --fix .` will both report issues and apply automatic fixes where possible.

## Tests are located in the `skiflux/tests/` directory. To run the tests, use:

```bash
poetry run pytest
```

### 4. Start the application

Run the Celery worker in one terminal:

```bash
poetry run celery -A skiflux_project worker -l info
```

Run the Celery beat in one terminal:

```bash
poetry run celery -A skiflux_project beat -l info
```

Run the Django server in another terminal:

```bash
poetry run python manage.py runserver
```

## 🔧 Payment System Overview

This backend supports wallet top-ups, saved cards, currency mapping, gateway
fee configuration, and withdrawal workflows.

### Supported gateways
* `flutterwave`
* `paystack`
* `stripe`
* `adyen`

Gateway implementations are located in `skiflux/gateways/` and are selected from `skiflux/gateways/registry.py`.

### Key payment models

The payment subsystem uses two main configuration models:
* `SystemFinancialConfig` (`skiflux/models/wallet.py`)
* `CurrencyConfig` (`skiflux/models/currency.py`)

#### `SystemFinancialConfig`
Controls global platform payment behavior:
* `enabled_topup_gateways` — payment gateways users may use to fund wallets.
* `enabled_withdrawal_gateways` — gateways allowed for admin withdrawal payout processing.
* `pass_gateway_fees_to_customer` — if `true`, gateway fees are charged on top of the requested top-up amount.
* `min_withdrawal_amount` and `withdrawal_fee_percentage` — withdrawal rules.
* `require_withdrawal_approval` — if `false`, withdrawals are auto-processed
  via the gateway immediately on request; if `true`, an admin must call
  `withdrawals/process`.
* `max_withdrawal_accounts` — how many payout destinations per user/creator.
* `max_saved_cards` and `card_verification_amount` — saved-card limits and
  Paystack verification charge (refunded to the card after add-card).
* `connect_payout_currency` — fiat currency for Stripe Connect payouts.
* `name_match_mode` — Paystack bank account name matching (`strict`/`fuzzy`/`relaxed`).
* `default_currency` — fallback currency for top-ups.

#### `CurrencyConfig`
Defines supported currencies and gateway compatibility:
* `currency_code` — e.g. `NGN`, `USD`
* `currency_name`
* `currency_symbol`
* `skillcoin_rate` — how much fiat equals one Skillcoin.
* `subunit_multiplier` — smallest-unit multiplier (e.g. `100` for NGN/USD, `1000` for KWD).
* `supported_gateways` — which gateways can process this currency.
* `is_active` — whether the currency may be used.

### User payment flow

#### 1. Initiate wallet top-up

Endpoint:
* `POST /api/v1/wallet/topup/initiate`

Request payload:
* `amount_fiat` (required)
* `currency` (optional, defaults to system default currency)
* `gateway_name` (optional)
* `redirect_url` (optional)
* `payment_method` (optional: `card`, `bank_transfer`, or `all` — default `all`)
* `save_card` (optional)
* `idempotency_key` (optional)

Process:
1. Validate the requested amount.
2. Resolve the requested currency via `CurrencyConfig`.
3. Ensure the selected gateway is enabled in `SystemFinancialConfig.enabled_topup_gateways`.
4. Create or reuse a pending `PaymentTransaction`.
5. Initiate the gateway payment and return a checkout URL.

Successful response includes:
* `transaction_id`
* `checkout_url`
* `tx_ref`
* `gateway_reference`
* `gateway`
* `amount_fiat`
* `gateway_fee`
* `charged_amount`
* `currency`

#### 2. Verify wallet top-up (or add-card)

Endpoint:
* `POST /api/v1/wallet/topup/verify`

Request payload:
* `tx_ref` (required) — prefixes: `skf-topup-*` (top-up), `skf-card-*` (add-card)
* `gateway_reference` (optional)

Process:
1. Load the `PaymentTransaction` by `tx_ref`.
2. Verify the gateway transaction status.
3. If successful: credit wallet (top-ups only), save card (when `save_card=true`),
   refund Paystack verification charge (add-card only).

Also used after `POST /wallet/cards/add` — same endpoint, same `tx_ref`.

#### 3. One-tap top-up with a saved card

Endpoint:
* `POST /api/v1/wallet/topup/charge-card`

Request payload:
* `saved_card_id` (required)
* `amount_fiat` (required)
* `currency` (optional)
* `idempotency_key` (optional — auto-generated if omitted; also accepts
  `Idempotency-Key` header)

Synchronous — no redirect. Returns the credited `PaymentTransaction`.

#### 4. Saved cards

| Action | Endpoint |
| --- | --- |
| Add card | `POST /api/v1/wallet/cards/add` |
| List cards | `GET /api/v1/wallet/cards` |
| Remove | `DELETE /api/v1/wallet/cards/{id}` |
| Set default | `POST /api/v1/wallet/cards/{id}/set-default` |

* **Paystack** — small verification charge, refunded to the card on success.
* **Stripe** — setup mode, no charge (`verification_amount: "0.00"`).
* Flow: `cards/add` → open `checkout_url` → `topup/verify` with `tx_ref`.

### Webhook processing

Webhook endpoints are defined in `skiflux/urls/webhooks.py`:
* `POST /api/v1/webhooks/payment/flutterwave/`
* `POST /api/v1/webhooks/payment/paystack/`
* `POST /api/v1/webhooks/payment/stripe/`

Webhook flow:
1. Verify the gateway signature.
2. Parse the event payload.
3. Identify the associated `tx_ref` (or `skf-wd-*` for Paystack transfers).
4. Finalize payment (credit wallet / save card / refund verification charge) or
   mark withdrawal completed.

**Local testing:**
* Paystack — `ngrok http 8000`, register
  `https://<subdomain>.ngrok-free.app/api/v1/webhooks/payment/paystack/`
* Stripe — `stripe listen --forward-to localhost:8000/api/v1/webhooks/payment/stripe/`,
  copy `whsec_...` to `STRIPE_WEBHOOK_SECRET`, restart Django

Stripe events that save cards: `checkout.session.completed`,
`setup_intent.succeeded`. Paystack `refund.*` events after add-card are
acknowledged but ignored.

## 🧑‍💼 Admin payment and financial configuration

### Financial configuration

Admin endpoint:
* `GET /api/v1/admin/finance/financial-config`
* `PATCH /api/v1/admin/finance/financial-config`

Superadmins can update:
* enabled top-up and withdrawal gateways
* default currency
* withdrawal limits and fees
* whether gateway fees are passed to customers
* cashback and creator revenue percentages
* maximum withdrawal accounts

### Currency management

Admin endpoint:
* `GET /api/v1/admin/finance/currencies`
* `POST /api/v1/admin/finance/currencies`

Admins can create or update currencies with:
* `currency_code`
* `currency_name`
* `currency_symbol`
* `skillcoin_rate`
* `supported_gateways`

### Gateway fee management

Admin endpoint:
* `GET /api/v1/admin/finance/gateway-fees`
* `POST /api/v1/admin/finance/gateway-fees/update`
* `DELETE /api/v1/admin/finance/gateway-fees/<config_id>`

This config controls:
* gateway fee percentage
* flat fee
* flat fee threshold
* VAT percentage and flat amount
* fee cap amount

### Payment transaction audit

Admin endpoint:
* `GET /api/v1/admin/finance/payment-transactions`

Filter by status, gateway, or user email.

## 💼 Wallet and withdrawal features

User wallet endpoints:
* `GET /api/v1/wallet/my-wallet`
* `GET /api/v1/wallet/my-transactions`
* `GET /api/v1/wallet/summary`
* `GET /api/v1/wallet/topup/methods`
* `POST /api/v1/wallet/topup/initiate`
* `POST /api/v1/wallet/topup/verify`
* `POST /api/v1/wallet/topup/charge-card`
* `POST /api/v1/wallet/cards/add`
* `GET /api/v1/wallet/cards`
* `DELETE /api/v1/wallet/cards/{id}`
* `POST /api/v1/wallet/cards/{id}/set-default`
* `GET /api/v1/wallet/withdrawals/methods`
* `GET /api/v1/wallet/withdrawals/banks`
* `POST /api/v1/wallet/withdrawals/accounts`
* `GET /api/v1/wallet/withdrawals/accounts/list`
* `DELETE /api/v1/wallet/withdrawals/accounts/{id}`
* `POST /api/v1/wallet/withdrawals/connect/onboard`
* `GET /api/v1/wallet/withdrawals/connect/status`
* `POST /api/v1/wallet/withdrawals/request`
* `GET /api/v1/wallet/withdrawals/requests`

Creator/admin self-service (same actions, prefix `/admin/wallet/my/`):
* Mirrors all user wallet endpoints above for the admin's own wallet.

Admin finance endpoints:
* `POST /api/v1/admin/finance/manual-adjustment`
* `POST /api/v1/admin/finance/toggle-lock`
* `POST /api/v1/admin/finance/issue-refund`
* `POST /api/v1/admin/finance/verify-integrity`
* `POST /api/v1/admin/finance/withdrawals/process`
* `POST /api/v1/admin/finance/withdrawals/reject`
* `GET /api/v1/admin/finance/withdrawals/requests`
* `GET /api/v1/admin/finance/ledger-audit`
* `GET /api/v1/admin/finance/platform-wallet`

## 📖 API Documentation

Once the server is running, access:
* Swagger UI: `http://localhost:8000/api/docs/`
* OpenAPI schema: `http://localhost:8000/api/schema/`

Flow guides:
* [Payment flows](docs/payment-flows.md) — top-ups, saved cards, webhooks,
  and integration test scripts
* [Withdrawal flows](docs/withdrawal-flows.md) — user/creator cash-out,
  Paystack bank + Stripe Connect, admin process/reject
* [Platform tasks](docs/platform-tasks.md)

## 🐳 Deployment scripts

The repository includes deployment scripts:
* `build.sh` — run migrations and prepare the app
* `start.sh` — start Gunicorn and Celery workers

## ⚠️ Payment readiness checklist

Before initiating a payment, confirm the following:
1. `.env` contains valid gateway secrets and webhook secrets.
2. `PUBLIC_API_BASE_URL` points to your API host.
3. `PAYMENT_REDIRECT_URL` points to a client callback or verification endpoint.
4. `SystemFinancialConfig.enabled_topup_gateways` includes the desired gateway.
5. `CurrencyConfig` exists for the requested currency and includes the gateway in `supported_gateways`.
6. `SystemFinancialConfig.pass_gateway_fees_to_customer` is set according to whether the customer should pay gateway processing fees.
7. Webhook URLs are registered in the gateway dashboard and match your deployment host.

## ✅ Summary

The SkiFlux backend is set up to support wallet top-ups, payment verification, webhook-based payment confirmation, and admin financial controls. The payment flow depends on:
* valid gateway secrets in environment variables
* enabled gateways in system configuration
* active currency definitions
* proper webhook registration

Use the admin finance endpoints to configure which payment gateways are allowed, how fees are handled, and which currencies are active.
