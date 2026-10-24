from django.urls import path

from apps.devlab import views

D = "api/v1/devlab"
urlpatterns = [
    path(f"{D}/models", views.models),
    path(f"{D}/models/<str:name>/check", views.model_check),
    path(f"{D}/datasets", views.dataset_list),
    path(f"{D}/jobs", views.jobs),
    path(f"{D}/jobs/<str:job_id>", views.job_detail),
    path(f"{D}/jobs/<str:job_id>/items", views.job_items),
    path(f"{D}/jobs/<str:job_id>/items/<str:item_id>", views.item_detail),
    path(f"{D}/jobs/<str:job_id>/start", views.job_start),
    path(f"{D}/jobs/<str:job_id>/cancel", views.job_cancel),
    path(f"{D}/jobs/<str:job_id>/delete", views.job_delete),
    path(f"{D}/jobs/<str:job_id>/export", views.job_export),
]
