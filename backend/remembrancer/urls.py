"""Public URL map.

Caddy routes only /api/*, /admin-ish path, /feed.xml, /media/* and /static/* here;
everything else goes to Next.js. Nothing below may claim a path outside that set.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from reviews.api import api
from reviews.feeds import ReviewsFeed

urlpatterns = [
    path(f"{settings.ADMIN_PATH}/", admin.site.urls),
    path("api/", api.urls),
    path("feed.xml", ReviewsFeed(), name="feed"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = f"{settings.SITE_NAME} admin"
admin.site.site_title = settings.SITE_NAME
admin.site.index_title = "Library and reviews"
