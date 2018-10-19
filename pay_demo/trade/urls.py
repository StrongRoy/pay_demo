from django.urls import path,include

from pay_demo.trade.views import (
    alipay_view,
    order_view,
OrderViewset,
)


from rest_framework.routers import DefaultRouter


router = DefaultRouter()
#订单相关url
router.register(r'orders', OrderViewset, base_name="orders")

app_name = "trade"
urlpatterns = [
    path('', include(router.urls)),
    path("alipay/return/", view=alipay_view, name="alipay"),
    # path('orders', view=order_view, name="orders")
]
