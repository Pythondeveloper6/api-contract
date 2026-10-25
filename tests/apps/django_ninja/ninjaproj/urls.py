from django.urls import path
from orders.api import api

urlpatterns = [path("api/", api.urls)]
