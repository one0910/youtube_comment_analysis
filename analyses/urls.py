from django.urls import path
from . import views

app_name = "analyses"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("analyses/new/", views.new_analysis, name="new_analysis"),
    path("analyses/videos/<int:video_id>/start/", views.start_analysis, name="start_analysis"),
    path("analyses/jobs/<uuid:analysis_job_id>/",views.analysis_job_detail,name="analysis_job_detail"),
]