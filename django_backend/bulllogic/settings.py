import os
from pathlib import Path
from dotenv import load_dotenv
try:
    import dj_database_url
except ImportError:
    dj_database_url = None

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR.parent / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', os.getenv('SECRET_KEY', 'django-insecure-change-this-in-production-now'))
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 't')
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'users',
    'trading',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.RequestTimingMiddleware',
    'core.middleware.LastSeenMiddleware',
]

ROOT_URLCONF = 'bulllogic.urls'

FRONTEND_DIST = BASE_DIR.parent / 'frontend' / 'dist'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [FRONTEND_DIST] if FRONTEND_DIST.exists() else [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'bulllogic.wsgi.application'

# ── Database Configuration (Google Cloud SQL / Postgres / SQLite) ─────────────
DATABASE_URL = os.getenv('DATABASE_URL')
parsed_db = None
if DATABASE_URL and dj_database_url:
    try:
        # Standardize postgresql scheme
        url = DATABASE_URL
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        parsed_db = dj_database_url.parse(url, conn_max_age=600, conn_health_checks=True)
    except Exception:
        parsed_db = None

if parsed_db:
    DATABASES = {'default': parsed_db}
elif os.getenv("DATABASE_TYPE") == "postgres":
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB', 'bulllogic'),
            'USER': os.getenv('POSTGRES_USER', 'postgres'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
            'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR.parent / 'instance' / 'bulllogic_django.db',
        }
    }

AUTH_USER_MODEL = 'users.User'

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'users.hashers.WerkzeugHasher',  # verifies Flask/Werkzeug scrypt + pbkdf2 hashes
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = False  # match naive datetimes

# ── Static Files (Whitenoise + React SPA) ────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_DIRS = []
if FRONTEND_DIST.exists():
    STATICFILES_DIRS.append(FRONTEND_DIST)

STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://localhost:5174',
    'http://localhost:5175',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
    'http://127.0.0.1:5175',
    'http://localhost:5000',
    'http://127.0.0.1:5000',
    'http://localhost:5001',
    'http://127.0.0.1:5001',
    'http://localhost:8002',
    'http://127.0.0.1:8002',
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Allow all in dev

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 86400 * 7  # 7 days
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False    # React reads it
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:5173',
    'http://localhost:5174',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
    'http://localhost:5000',
    'http://127.0.0.1:5000',
    'http://localhost:5001',
    'http://127.0.0.1:5001',
    'http://localhost:8002',
    'http://127.0.0.1:8002',
]

# Email
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
