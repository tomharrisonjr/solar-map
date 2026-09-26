from rest_framework.routers import DefaultRouter

from facilities.views import SolarFacilityViewSet

router = DefaultRouter()
router.register("facilities", SolarFacilityViewSet, basename="facility")

urlpatterns = router.urls
