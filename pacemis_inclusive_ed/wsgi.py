"""
WSGI config for pacemis_inclusive_ed project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Prefer explicit path at project root; fall back to auto-discovery
project_root = Path(__file__).resolve().parent
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path if env_path.exists() else find_dotenv())


from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pacemis_inclusive_ed.settings")

application = get_wsgi_application()
