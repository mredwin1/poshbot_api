from django.urls import path
from rest_framework_nested import routers

from . import views

router = routers.SimpleRouter()

router.register("posh-users", views.PoshUserViewSet, basename="posh-users")
router.register("listings", views.ListingViewSet, basename="listings")
router.register("campaigns", views.CampaignViewSet, basename="campaigns")

listings_router = routers.NestedSimpleRouter(router, "listings", lookup="listing")
listings_router.register("images", views.ListingImageViewSet, basename="listing-images")

campaigns_router = routers.NestedSimpleRouter(router, "campaigns", lookup="campaign")
campaigns_router.register("logs", views.LogGroupViewSet, basename="campaign-logs")

urlpatterns = [
    path("auth/token/create/", views.TokenObtainPairView.as_view(), name="token")
]
urlpatterns += router.urls
urlpatterns += listings_router.urls
urlpatterns += campaigns_router.urls
