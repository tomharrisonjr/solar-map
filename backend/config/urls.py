from django.contrib import admin
from django.urls import include, path

from facilities.views import MapView, tile_view

urlpatterns = [
    path("", MapView.as_view(), name="map"),
    path("tiles/<int:z>/<int:x>/<int:y>.mvt", tile_view, name="tile"),
    path("admin/", admin.site.urls),
    path("api/", include("facilities.urls")),
]
