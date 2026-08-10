from django.urls import path

from . import views

app_name = "itr"

urlpatterns = [
    path("set-locale/<str:locale>/", views.set_locale, name="set_locale"),
    path("returns/", views.return_list, name="return_list"),
    path("returns/new/", views.return_create, name="return_create"),
    path("returns/<uuid:return_id>/personal-info/", views.personal_info, name="personal_info"),
    path("returns/<uuid:return_id>/gross-total-income/", views.gross_total_income, name="gross_total_income"),
    path("returns/<uuid:return_id>/total-deductions/", views.total_deductions, name="total_deductions"),
    path("returns/<uuid:return_id>/tax-paid/", views.tax_paid, name="tax_paid"),
    path("returns/<uuid:return_id>/tax-liability/", views.tax_liability, name="tax_liability"),
    path("returns/<uuid:return_id>/tax-summary/", views.tax_summary, name="tax_summary"),
    path("returns/<uuid:return_id>/validation/", views.validation, name="validation"),
]
