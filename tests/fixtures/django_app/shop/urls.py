"""Django URL configuration for testing."""

from django.urls import include, path

from . import views

urlpatterns = [
    path("orders/", views.order_list, name="order-list"),
    path("orders/<int:pk>/", views.order_detail, name="order-detail"),
    path("orders/<int:pk>/invoice/", views.order_invoice, name="order-invoice"),
    path("accounts/", include("accounts.urls")),
]
