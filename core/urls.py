from rest_framework_nested import routers
from . import views

router = routers.SimpleRouter()

router.register('posh-users', views.PoshUserViewSet, basename='posh-users')
router.register('listings', views.ListingViewSet, basename='listings')
router.register('campaigns', views.CampaignViewSet, basename='campaigns')

listings_router = routers.NestedSimpleRouter(router, 'listings', lookup='listing')
listings_router.register('images', views.ListingImageViewSet, basename='listing-images')

urlpatterns = router.urls
urlpatterns += listings_router.urls
