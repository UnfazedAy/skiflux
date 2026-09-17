import os

from django.core.wsgi import get_wsgi_application

if os.environ.get("USE_GEVENT") == "True":
    from gevent import monkey
    from psycogreen.gevent import patch_psycopg

    monkey.patch_all()
    patch_psycopg()
    print("Gevent monkey patching applied for VPS!")
else:
    print("Running standard unpatched Python for Railway!")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "skiflux_project.settings")

application = get_wsgi_application()
