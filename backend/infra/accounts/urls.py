from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('signup/', views.SignUpView.as_view(), name='signup'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('mfa/setup/', views.MfaSetupView.as_view(), name='mfa_setup'),
    path('mfa/verify/', views.MfaVerifyView.as_view(), name='mfa_verify'),
    path('forgot-password/', views.ForgotPasswordIdentifyView.as_view(), name='forgot_password'),
    path('forgot-password/verify/', views.ForgotPasswordVerifyView.as_view(), name='forgot_password_verify'),
    path('forgot-password/reset/', views.ForgotPasswordResetView.as_view(), name='forgot_password_reset'),
    path('settings/', views.SettingsView.as_view(), name='settings'),
]
