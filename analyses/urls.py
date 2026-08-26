from django.urls import path
from . import views

app_name = "analyses"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("analyses/new/", views.new_analysis, name="new_analysis"),
]