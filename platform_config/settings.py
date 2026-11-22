import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
for line in (BASE_DIR / '.env').read_text(encoding='utf-8-sig').splitlines() if (BASE_DIR / '.env').exists() else []:
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'
SECRET_KEY = os.getenv('SECRET_KEY', 'development-only-JobSearch-change-before-deploying')
if not DEBUG and (len(SECRET_KEY) < 32 or SECRET_KEY.startswith('development-only')):
    raise ImproperlyConfigured('Set a strong SECRET_KEY before production deployment')
ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [u.strip() for u in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if u.strip()]
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
                  'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'careers']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware',
              'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
              'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
              'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
              'careers.middleware.PlatformHeadersMiddleware']
ROOT_URLCONF = 'platform_config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request',
               'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages',
               'careers.context.platform_context']}}]
WSGI_APPLICATION = 'platform_config.wsgi.application'
DATA_DIR = Path(os.getenv('DATA_DIR', str(BASE_DIR / 'data')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
# Reuse existing installations without moving an open SQLite/WAL database.
legacy_database = DATA_DIR / 'jobabc.sqlite3'
default_database = legacy_database if legacy_database.exists() else DATA_DIR / 'JobSearch.sqlite3'
DATABASES = {'default': dj_database_url.config(default='sqlite:///' + default_database.as_posix(), conn_max_age=60)}
if DATABASES['default']['ENGINE'].endswith('sqlite3'):
    DATABASES['default']['CONN_MAX_AGE'] = 0
    DATABASES['default']['OPTIONS'] = {
        'timeout': 30,
        # Acquire the writer slot before a read-then-write transaction starts.
        # This avoids SQLite's immediate failed DEFERRED lock upgrades.
        'transaction_mode': 'IMMEDIATE',
        'init_command': 'PRAGMA journal_mode=WAL;',
    }
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/jobs/'
LOGOUT_REDIRECT_URL = '/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG and os.getenv('SECURE_SSL_REDIRECT', 'true').lower() == 'true'
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
if os.getenv('TRUST_PROXY_HTTPS', 'false').lower() == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
MAX_RESUME_BYTES = 5 * 1024 * 1024
AI_PROVIDERS = [p.strip() for p in os.getenv('AI_PROVIDERS', 'gemini,groq,openai').split(',') if p.strip()]
AI_MODELS = {'gemini': os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite'),
             'groq': os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'),
             'openai': os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')}
AI_DAILY_USER_LIMIT = int(os.getenv('AI_DAILY_USER_LIMIT', '8'))
AI_DAILY_GLOBAL_LIMIT = int(os.getenv('AI_DAILY_GLOBAL_LIMIT', '100'))
AI_DAILY_TOKEN_BUDGET = int(os.getenv('AI_DAILY_TOKEN_BUDGET', '200000'))
DISCOVERY_MAX_QUERIES = int(os.getenv('DISCOVERY_MAX_QUERIES', '4'))
DISCOVERY_MAX_PAGES = int(os.getenv('DISCOVERY_MAX_PAGES', '8'))
DISCOVERY_MAX_BOARDS = int(os.getenv('DISCOVERY_MAX_BOARDS', '30'))
TAVILY_MONTHLY_LIMIT = max(0, int(os.getenv('TAVILY_MONTHLY_LIMIT', '800')))
BRAVE_MONTHLY_LIMIT = max(0, int(os.getenv('BRAVE_MONTHLY_LIMIT', '800')))
JOB_API_DAILY_LIMIT = max(0, int(os.getenv('JOB_API_DAILY_LIMIT', '40')))
DEMO_MODE = os.getenv('DEMO_MODE', 'false').lower() == 'true'
DEFAULT_FROM_EMAIL = 'noreply@localhost'
