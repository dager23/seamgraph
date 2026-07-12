"""Django views for testing."""

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse


def order_list(request):
    return render(request, "shop/order_list.html", {"title": "Orders"})


def order_detail(request, pk):
    api_key = settings.STRIPE_API_KEY
    return render(request, "shop/order_detail.html", {"pk": pk, "api_key": api_key})


def order_invoice(request, pk):
    return render(request, "shop/invoice.html", {"pk": pk})


def order_redirect(request, pk):
    return redirect(reverse("order-detail", kwargs={"pk": pk}))
