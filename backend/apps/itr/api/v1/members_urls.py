from django.urls import path

from . import members_views as views

app_name = 'members_api_v1'

urlpatterns = [
    path('', views.members_list, name='members-list'),
    path('<uuid:member_id>/', views.member_detail, name='member-detail'),
]
