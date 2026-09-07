from django.urls import path
from . import views
from .report_v2_views import report_v2_preview, report_v2_real_preview

app_name = "analyses"

urlpatterns = [
    path("analyses/reports/preview/v2/", report_v2_preview, name="report_v2_preview"),
    path("analyses/reports/preview/v2/real/", report_v2_real_preview, name="report_v2_real_preview"),
    path("", views.overview, name="overview"),
    path("analyses/new/", views.new_analysis, name="new_analysis"),
    path("analyses/videos/<int:video_id>/start/", views.start_analysis, name="start_analysis"),
    path("analyses/jobs/<uuid:analysis_job_id>/",views.analysis_job_detail,name="analysis_job_detail"),
    path("analyses/jobs/<uuid:analysis_job_id>/progress/",views.analysis_job_progress,name="analysis_job_progress"),
    path("analyses/jobs/<uuid:analysis_job_id>/report/",views.analysis_report_detail,name="analysis_report_detail"),
]
