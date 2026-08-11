from django.urls import path

from . import views

app_name = 'catalog_api_v1'

urlpatterns = [
    path('', views.services_list, name='services-list'),
]
