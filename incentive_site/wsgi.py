import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "incentive_site.settings")

application = get_wsgi_application()
app = application  # Vercel's Python runtime looks for a module-level "app".
