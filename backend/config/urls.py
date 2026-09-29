from django.contrib import admin
from django.urls import include, path

from facilities.views import MapView

urlpatterns = [
    path("", MapView.as_view(), name="map"),
    path("admin/", admin.site.urls),
    path("api/", include("facilities.urls")),
]
