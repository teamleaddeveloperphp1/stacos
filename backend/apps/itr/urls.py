from django.urls import path

from . import views

app_name = "itr"

urlpatterns = [
    path("members/", views.member_list, name="member_list"),
    path("members/add/", views.member_add, name="member_add"),
    path("members/<uuid:member_id>/edit/", views.member_edit, name="member_edit"),
    path("members/<uuid:member_id>/delete/", views.member_delete, name="member_delete"),
    path("members/<uuid:member_id>/continue/", views.member_continue, name="member_continue"),
    path("returns/", views.return_list, name="return_list"),
    path("returns/new/", views.return_create, name="return_create"),
    path("returns/<uuid:return_id>/filing-section/", views.filing_section, name="filing_section"),
    path("returns/<uuid:return_id>/personal-info/", views.personal_info, name="personal_info"),
    path("returns/<uuid:return_id>/gross-total-income/", views.gross_total_income, name="gross_total_income"),
    path("returns/<uuid:return_id>/total-deductions/", views.total_deductions, name="total_deductions"),
    path("returns/<uuid:return_id>/tax-paid/", views.tax_paid, name="tax_paid"),
    path("returns/<uuid:return_id>/tax-liability/", views.tax_liability, name="tax_liability"),
    path("returns/<uuid:return_id>/tax-summary/", views.tax_summary, name="tax_summary"),
    path("returns/<uuid:return_id>/validation/", views.validation, name="validation"),
]
