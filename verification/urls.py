from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("upload/", views.upload, name="upload"),
    path("result/<int:pk>/", views.result, name="result"),
    path("result/<int:pk>/image/", views.screenshot, name="screenshot"),
    path("history/", views.history, name="history"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    # PayGuard features
    path("timeline/", views.timeline, name="timeline"),
    path("family-tree/", views.family, name="family"),
    path("fraud-chain/", views.chain, name="chain"),
    path("what-if/", views.whatif, name="whatif"),
    path("what-if/api/", views.whatif_api, name="whatif_api"),
    path("export.csv", views.export_csv, name="export_csv"),
    path("demo/load/", views.demo_load, name="demo_load"),
    path("demo/clear/", views.demo_clear, name="demo_clear"),
]
