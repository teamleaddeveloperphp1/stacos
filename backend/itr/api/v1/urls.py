from django.urls import path

from . import views

app_name = 'itr_api_v1'

urlpatterns = [
    path('returns/', views.returns_list, name='returns-list'),
    path('returns/<uuid:return_id>/', views.return_detail, name='return-detail'),
    path('returns/<uuid:return_id>/filing-section/', views.filing_section_view, name='filing-section'),
    path('returns/<uuid:return_id>/screens/<str:screen>/', views.screen_detail, name='screen-detail'),
    path('returns/<uuid:return_id>/screens/<str:screen>/confirm/', views.screen_confirm, name='screen-confirm'),
    path('returns/<uuid:return_id>/verification/', views.save_verification_view, name='verification'),
    path('returns/<uuid:return_id>/tax-summary/confirm/', views.confirm_tax_summary_view, name='tax-summary-confirm'),
    path('returns/<uuid:return_id>/computation/', views.computation_view, name='computation'),
    path('returns/<uuid:return_id>/validate/', views.validate_view, name='validate'),
    path('returns/<uuid:return_id>/generate-json/', views.generate_json_view, name='generate-json'),
    path('returns/<uuid:return_id>/import-json/', views.import_json_view, name='import-json'),
    path('returns/<uuid:return_id>/advisories/acknowledge/', views.acknowledge_view, name='acknowledge'),
    path('returns/<uuid:return_id>/regime-comparison/', views.regime_comparison_view, name='regime-comparison'),
    path('returns/<uuid:return_id>/documents/<str:kind>/', views.document_view, name='document'),
]
