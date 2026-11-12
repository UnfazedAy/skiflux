# SkiFlux — Scalable EdTech & Social Learning Backend

SkiFlux is a Django REST Framework backend for an online learning and creator
community. It brings learners, educators, and platform administrators together
around structured video lessons, learner submissions, discussion, and creator
monetization. The API also provides account management, moderation, support,
notifications, and financial workflows for the platform.

## Contents

- [Key features](#key-features)
- [Technology stack](#technology-stack)
- [System architecture](#system-architecture)
- [Engineering highlights](#selected-engineering-highlights)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Environment variables](#environment-variables)
- [API overview](#api-overview)
- [Testing and code quality](#testing-and-code-quality)
- [Development status and limitations](#development-status-and-limitations)
- [Maintainers and contributions](#maintainers-and-contributions)

## Key features

The features below are present in the repository. Integrations that depend on
external services require valid credentials and provider-side configuration.

### Authentication and access control

- Email registration and verification, password reset, token refresh, and
  logout.
- JWT authentication with separate signing secrets and authentication classes
  for learner and admin accounts.
- Social authentication flows for Google, Apple, and Facebook mobile sign-in.
- Configurable admin roles and permissions, super-admin checks, account
  activation and suspension controls, and failed-login lockout handling.
- Creator access through the admin-user/studio model, with verification and
  profile checks.

### Learning content and creator tools

- Creator studio workflows for seasons, episodes, episode tasks, and learner
  submissions.
- Learner-facing episode discovery, search, recommendations, likes, saves,
  comments, follows, ratings, and task submissions.
- Admin review queues and actions for episodes and task submissions.
- Learning progress and gamification features, including streaks, badges, and
  platform tasks.

### Video and media

- Upload handoff through S3-compatible object storage, configured using the
  legacy `MINIO_*` setting names (the configuration supports Cloudflare R2).
- Cloudinary storage and video processing, including asynchronous eager
  transformations and HLS readiness checks.
- Signed media URLs and a Cloudinary webhook that queues processing completion
  handling.
- Upload and processing state transitions with creator email notifications.

### Moderation and community safety

- Gemini-based comment classification runs as a Celery task.
- AI classifications can flag comments for administrative review; moderation
  actions, user reports, action logs, and suspension management are also
  implemented.
- Suspension expiry is handled by a scheduled task. Automatic suspension
  based on AI confidence is not enabled in the current task implementation.

### Support and email

- Support tickets, ticket messages, assignment, resolution, reopening, and
  satisfaction scores.
- Scheduled IMAP inbox polling to create or update tickets from incoming email,
  with basic subject/body categorization and threading.
- Admin replies are sent over SMTP; application emails such as account and
  upload notifications are sent asynchronously through Brevo.

### Payments and creator monetization

- Gateway adapters for Flutterwave, Paystack, Stripe, and Adyen.
- Wallet top-ups, saved cards, currency and gateway fee configuration, a
  Skillcoin transaction ledger, and withdrawal requests.
- Admin finance operations for reviewing transactions, processing withdrawals,
  refunds, adjustments, and wallet integrity checks.
- Stripe Connect onboarding and creator revenue workflows are represented in
  the codebase.
- Payment webhook routes are registered for Flutterwave, Paystack, and Stripe;
  an Adyen adapter exists, but an Adyen webhook route is not registered.

### Notifications and administration

- In-app notifications, device registration, Firebase Cloud Messaging push
  delivery, user notification preferences, and platform announcements.
- Celery tasks for email, push delivery, content processing, moderation,
  reminders, support inbox polling, and other scheduled work.
- Admin dashboards and tools for users, creators, content review, moderation,
  finance, notifications, support, platform configuration, and activity logs.

## Technology stack

| Technology | Category | Purpose |
| --- | --- | --- |
| Python 3.12 | Language | Backend runtime |
| Django 6.0 | Web framework | Application configuration, ORM, and HTTP foundation |
| Django REST Framework | API framework | REST endpoints, authentication integration, and serializers |
| PostgreSQL | Database | Primary application database; configured with `psycopg2` |
| Redis | Cache and broker | Django cache plus Celery broker and result backend |
| Celery | Background processing | Asynchronous jobs and periodic tasks |
| PyJWT | Authentication | Custom learner and admin JWT creation and validation |
| drf-spectacular | API documentation | OpenAPI schema and Swagger UI |
| Cloudinary | Media | Private media assets and video transformations/streaming |
| S3-compatible object storage (Cloudflare R2 configuration) | Temporary media storage | Cross-process upload handoff via `boto3` |
| Google Gemini (`gemini-2.5-flash`) | AI moderation | Comment classification |
| Flutterwave, Paystack, Stripe, Adyen | Payments | Gateway-specific payment and payout integrations |
| Brevo | Email delivery | Application email delivery over its SMTP API |
| IMAP and SMTP | Support email | Support inbox ingestion and email replies |
| Firebase Admin SDK | Push notifications | Firebase Cloud Messaging delivery |
| Poetry | Dependency management | Python package and virtual-environment management |
| Pytest and Ruff | Testing and code quality | Test execution, linting, and formatting checks |
| Docker Compose | Local infrastructure | Optional local PostgreSQL and Redis services |

## System architecture

The backend separates HTTP handling, validation, business workflows, and
persistence through the following path:

**Views → Serializers → Services → Repositories → Models**

Celery workers consume queued tasks through Redis. Celery Beat schedules
recurring jobs. Redis also backs Django's non-test cache; tests configure an
in-memory cache. Media uploads use S3-compatible object storage for temporary
handoff and Cloudinary for media storage and processing. The Cloudinary
completion webhook queues a task to update episode state. Services also call
payment gateways, Gemini, Brevo, support mail servers, and Firebase as needed.

```mermaid
flowchart LR
    Client[API client] --> URLs[Django URL configuration]
    URLs --> Views[Views]
    Views --> Serializers[Serializers]
    Serializers --> Services[Services]
    Services --> Repositories[Repositories]
    Repositories --> Models[Django models]
    Models --> PostgreSQL[(PostgreSQL)]

    Services --> Cache[Redis cache]
    Services --> Broker[Redis Celery broker]
    Beat[Celery Beat] --> Broker
    Broker --> Worker[Celery workers]
    Worker --> Services

    Services --> Gateways[Payment gateway adapters]
    Gateways --> Providers[Flutterwave / Paystack / Stripe / Adyen]
    Services --> Gemini[Google Gemini]
    Services --> Staging[S3-compatible object storage]
    Services --> Cloudinary[Cloudinary media processing]
    Cloudinary --> MediaHook[Cloudinary webhook]
    MediaHook --> Broker
    Worker --> Email[Brevo and support mail servers]
    Worker --> Push[Firebase Cloud Messaging]
```

## Selected engineering highlights

- **Asynchronous workflows:** Celery tasks handle operations such as email,
  push delivery, comment moderation, and media-processing callbacks. Beat
  schedules recurring work, including reminders, token cleanup, suspension
  expiry, and support inbox polling.
- **Payment deduplication and ledger controls:** Top-up initiation stores
  user-scoped idempotency keys and checks for existing pending transactions.
  Payment verification uses database transactions and row locking, and wallet
  credits carry transaction references and idempotency keys. Management
  commands and tests cover ledger and wallet invariants.
- **Provider-specific payment adapters:** A common gateway interface and
  registry select configured providers while payment services handle the
  shared transaction workflow. Provider webhook coverage is not uniform:
  Flutterwave, Paystack, and Stripe have registered webhook routes; Adyen does
  not.
- **Separate JWT trust boundaries:** Learner and administrator tokens use
  distinct secrets and authentication classes. Admin authorization is backed
  by role/permission checks, and refresh tokens can be blacklisted.
- **Cloud video-processing lifecycle:** Upload processing is asynchronous.
  A signed Cloudinary callback is validated, queued, and used to transition
  episode state when the expected HLS transformation is ready.
- **Moderation with human review:** Gemini classification can flag comments
  for review, while administrative actions and audit records remain available
  for human moderation. AI-triggered automatic suspension is currently
  disabled.
- **Support by email:** Scheduled mailbox polling ingests unseen messages,
  links replies to existing tickets when possible, and creates ticket records.
  Admin replies are sent through SMTP and recorded in the ticket thread.

These are descriptions of code paths, not claims about measured throughput,
availability, or production operation.

## Project structure

```text
.
├── .github/
│   └── workflows/
│       └── ci.yml
├── README.md
└── skiflux_project/
    ├── Dockerfile
    ├── docker-compose.yml
    ├── docker-compose.prod.yml
    ├── env-example
    ├── manage.py
    ├── poetry.lock
    ├── pyproject.toml
    ├── pytest.ini
    ├── scripts/
    │   ├── beat.sh
    │   ├── build.sh
    │   ├── deploy.sh
    │   ├── local_start.sh
    │   ├── start.sh
    │   └── worker.sh
    ├── skiflux/
    │   ├── deps/
    │   ├── gateways/
    │   ├── management/commands/
    │   ├── migrations/
    │   ├── models/
    │   ├── repositories/
    │   ├── serializers/
    │   ├── services/
    │   ├── tasks/
    │   ├── urls/
    │   ├── utils/
    │   └── views/
    ├── skiflux_project/
    │   ├── celery.py
    │   ├── settings.py
    │   ├── urls.py
    │   └── wsgi.py
    └── tests/
        ├── api_v1/
        ├── concurrency/
        ├── gateways/
        ├── services/
        ├── tasks/
        └── webhooks/
```

## Getting started

### Prerequisites

- Python 3.12
- Poetry
- Docker with the Compose plugin, or a separately managed PostgreSQL and Redis
  instance
- Credentials for the external integrations you intend to exercise

The regular application settings use `DATABASE_URL` for the database and
default to a local Redis URL. The test settings switch to an in-memory SQLite
database and local-memory cache.

### Clone and configure

```bash
git clone https://github.com/UnfazedAy/skiflux.git
cd skiflux/skiflux_project
poetry install --with dev
cp env-example .env
```

Edit `.env` before starting Django. The checked-in `env-example` contains
placeholders, and `PAYLOAD_ENCRYPTION_KEY` is blank there; set it to a valid
Fernet key for payment and saved-card workflows. For example, generate a new
key with:

```bash
poetry run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the generated key into your local `.env`; do not commit it.

### Start PostgreSQL and Redis

From `skiflux_project/`, start the Compose database and Redis services:

```bash
docker compose up -d db redis
```

The local Compose database uses the development-only credentials declared in
`docker-compose.yml`. Set `DATABASE_URL` in `.env` to
`postgres://skiflux:skiflux@localhost:5432/skiflux` for this local setup.
Alternatively, point `DATABASE_URL` and `REDIS_URL` at your own services.

### Apply migrations and run the API

```bash
poetry run python manage.py migrate
poetry run python manage.py runserver
```

The development server listens on `http://127.0.0.1:8000` by default. The
built-in API documentation is available at
`http://127.0.0.1:8000/api/docs/`.

### Run background processing

Run each command in a separate terminal from `skiflux_project/`:

```bash
poetry run celery -A skiflux_project worker --loglevel=info
```

```bash
poetry run celery -A skiflux_project beat --loglevel=info
```

Celery uses `REDIS_URL` as its broker and result backend. Some scheduled or
on-demand tasks need their respective external credentials; for example,
support inbox polling needs the support mailbox credentials.

## Environment variables

`env-example` is the canonical variable-name template. The application reads
some settings as mandatory at Django configuration time, while others are
needed only for a particular integration. Never place production credentials
in documentation or source control.

| Variable(s) | Requirement | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Required for normal application settings | Database connection URL |
| `SECRET_KEY` | Set a non-default value outside local testing | Django secret and fallback signing key |
| `DEFAULT_FROM_EMAIL`, `BREVO_API_KEY` | Required by settings | Sender identity and Brevo application email delivery |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Required by settings | Cloudinary SDK configuration |
| `PAYLOAD_ENCRYPTION_KEY` | Required for payment/card workflows; use a valid Fernet key | Encryption of sensitive gateway payload data |
| `REDIS_URL` | Recommended; required for Celery and the configured non-test cache | Redis connection URL (defaults to `redis://localhost:6379/0`) |
| `USER_JWT_SECRET`, `ADMIN_JWT_SECRET` | Optional; default to `SECRET_KEY` | Separate learner and admin JWT signing keys |
| `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` | Set for each deployment | Django host validation and browser-origin policy |
| `ACCESS_TOKEN_LIFETIME_MINUTES`, `REFRESH_TOKEN_LIFETIME_DAYS`, `PASSWORD_RESET_TOKEN_LIFETIME` | Optional | Token and password-reset lifetimes |
| `PUBLIC_API_BASE_URL`, `CLOUDINARY_EAGER_WEBHOOK_URL` | Optional; set for reachable callbacks | Public API address and Cloudinary eager-processing callback |
| `MINIO_ENDPOINT_URL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_NAME` | Needed for upload handoff | S3-compatible storage configuration; names are retained from an earlier MinIO-compatible implementation |
| `FIREBASE_SERVICE_ACCOUNT`, `FIREBASE_SERVICE_ACCOUNT_PATH` | Needed for FCM delivery | Firebase service-account JSON or path to a service-account file |
| `GEMINI_API_KEY` | Needed for AI comment moderation | Google Gemini API access |
| `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_WEBHOOK_SECRET` | Needed for Flutterwave payments/webhooks | Flutterwave credentials |
| `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY` | Needed for Paystack payment flows | Paystack credentials |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` | Needed for Stripe payments/webhooks | Stripe credentials |
| `ADYEN_API_KEY`, `ADYEN_MERCHANT_ACCOUNT`, `ADYEN_ENVIRONMENT`, `ADYEN_WEBHOOK_SECRET` | Needed for Adyen workflows | Adyen credentials and environment selection |
| `PAYMENT_REDIRECT_URL` | Optional; defaults to a SkiFlux app callback URI | Payment checkout return target |
| `SUPPORT_EMAIL_HOST`, `SUPPORT_EMAIL_PORT`, `SUPPORT_EMAIL_USERNAME`, `SUPPORT_EMAIL_PASSWORD` | Needed for inbox polling | IMAP support mailbox configuration |
| `SUPPORT_SMTP_HOST`, `SUPPORT_SMTP_PORT` | Needed for support email replies | SMTP server configuration; uses the support mailbox credentials |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Needed for Google social sign-in | Google OAuth configuration |
| `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `FACEBOOK_REDIRECT_URI` | Needed for Facebook mobile sign-in | Facebook app configuration |
| `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`, `APPLE_REDIRECT_URI` | Needed for Apple sign-in | Apple sign-in configuration |
| `SENTRY_DSN` | Optional | Enables Sentry Django/Celery integration |
| `DB_CONN_MAX_AGE`, `DB_DISABLE_CURSORS`, `TEST_DATABASE_NAME`, `DEBUG` | Optional | Database connection and local/test settings |

## API overview

All application endpoints are mounted under `/api/v1/`. Representative routes
from the URL configuration include:

| API group | Example endpoints |
| --- | --- |
| Health and authentication | `GET /api/v1/health/`, `POST /api/v1/auth/signup`, `POST /api/v1/auth/login`, `POST /api/v1/auth/token/refresh` |
| Learner content | `GET /api/v1/seasons`, `GET /api/v1/episodes/{episode_id}`, `POST /api/v1/episodes/comment`, `POST /api/v1/episodes/task/submit` |
| Creator studio | `POST /api/v1/creator/create-season`, `POST /api/v1/creator/create-episode`, `POST /api/v1/creator/episode/{id}/reupload-video` |
| Wallet and payments | `POST /api/v1/wallet/topup/initiate`, `POST /api/v1/wallet/topup/verify`, `POST /api/v1/wallet/withdrawals/request` |
| Admin | `GET /api/v1/admin/dashboard/overview`, `GET /api/v1/admin/content/episodes/review`, `GET /api/v1/admin/roles` |
| Support | `GET /api/v1/admin/support/tickets/`, `POST /api/v1/admin/support/tickets/{ticket_id}/reply/` |
| Webhooks | `POST /api/v1/webhooks/payment/flutterwave/`, `POST /api/v1/webhooks/payment/paystack/`, `POST /api/v1/webhooks/payment/stripe/`, `POST /api/v1/webhooks/cloudinary/eager/` |

The generated OpenAPI schema and Swagger UI are served at
`/api/schema/` and `/api/docs/`, respectively, when the application is running.

## Testing and code quality

Run the test suite from `skiflux_project/`:

```bash
poetry run pytest
```

Tests use the project's pytest/Django configuration and in-memory SQLite
settings. Ruff formatting and lint checks are:

```bash
poetry run ruff format --check .
poetry run ruff check .
```

The GitHub Actions workflow defines Pytest, Ruff formatting, and Ruff lint jobs.
Those jobs are gated to pull requests; the workflow is configured for pull
requests targeting `dev` and pushes to `main`.

## Development status and limitations

This repository documents the implementation currently present in the backend;
it does not assert that every external integration is configured or operating
in a deployed environment.

- A fresh checkout needs local environment values and credentials for the
  services being used. The Firebase service-account file is not tracked.
- Adyen payment code exists, but the registered payment webhook endpoints
  cover Flutterwave, Paystack, and Stripe only.
- AI moderation currently flags comments; the automatic suspension option in
  the moderation task is disabled.
- Redis, PostgreSQL, Cloudinary, email, payment, AI, and push workflows depend
  on local services or provider credentials. Their end-to-end operation
  requires manual configuration and testing.
- The default host and CORS settings are permissive. Configure explicit
  `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` values for the target environment.
- Docker and deployment scripts are present, but their presence alone does not
  establish that a production deployment has been validated.

## Maintainers and contributions

The project metadata in `skiflux_project/pyproject.toml` lists Mandel,
Ayomide, and Areegbe David as project authors. No license file is present in
the repository; no license terms are implied here.

Contributions should include focused tests for behavior changes and pass the
pytest and Ruff checks above. Please avoid committing `.env` files, service
account keys, or other credentials.
