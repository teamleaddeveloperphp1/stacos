from django.urls import path

from . import views

app_name = 'catalog'

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('services/<slug:slug>/', views.ServiceView.as_view(), name='service'),
]
