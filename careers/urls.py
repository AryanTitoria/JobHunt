from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'), path('signup/', views.register, name='signup'),
    path('login/', views.PlatformLoginView.as_view(), name='login'), path('logout/', LogoutView.as_view(), name='logout'),
    path('resume/', views.resume_view, name='resume'), path('profile/', views.profile_view, name='profile'),
    path('jobs/', views.jobs, name='jobs'), path('jobs/refresh/', views.refresh_jobs, name='refresh-jobs'),
    path('jobs/<uuid:job_id>/', views.job_detail, name='job-detail'),
    path('jobs/<uuid:job_id>/open/', views.open_job, name='open-job'),
    path('jobs/<uuid:job_id>/review/', views.request_review, name='request-review'),
    path('jobs/<uuid:job_id>/state/', views.toggle_state, name='toggle-state'),
    path('jobs/<uuid:job_id>/tailor/',views.create_tailored,name='create-tailored'),
    path('jobs/<uuid:job_id>/interpret/',views.interpret_job,name='interpret-job'),
    path('tailored/<int:draft_id>/',views.tailored_detail,name='tailored-detail'),
    path('sources/', views.sources_view, name='sources'), path('api/tasks/', views.task_status, name='task-status'),
    path('account/export/', views.export_data, name='export-data'),
    path('account/delete-resumes/', views.delete_resumes, name='delete-resumes'),
    path('health/', views.health, name='health'),
]
