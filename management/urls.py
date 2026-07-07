from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('complaint/edit/<str:complaint_id>/', views.edit_complaint, name='edit_complaint'),
    path('complaint/delete/<str:complaint_id>/', views.delete_complaint, name='delete_complaint'),
    path('login/', LoginView.as_view(template_name='management/login.html'), name='login'),
    path('logout/', LogoutView.as_view(template_name='management/logout_success.html'), name='logout'),
    path('logout-success/', views.logout_success, name='logout_success'),
    path('complaints/', views.complaint_list, name='complaint_list'),
    path('profile/', views.profile_settings, name='profile_settings'),
    path('', views.index, name='index'),
    path('add-car-details/', views.add_car_details, name='add_car_details'),
    path('car-details/', views.car_details, name='car_details'),
    path('delete-car-detail/<int:year_range_id>/', views.delete_car_detail, name='delete_car_detail'),
    path('edit-car/<int:car_id>/', views.edit_car_detail, name='edit_car_detail'),
    path('master-settings/', views.master_settings, name='master_settings'),
    path('edit-master-setting/<int:setting_id>/', views.edit_master_setting, name='edit_master_setting'),
    path('delete-master-setting/<int:setting_id>/', views.delete_master_setting, name='delete_master_setting'),
    path('add-complaint/', views.add_complaint, name='add_complaint'),
    path('api/models/<int:brand_id>/', views.get_models, name='get_models'),
    path('api/sub_models/<int:model_id>/', views.get_sub_models, name='get_sub_models'),
    path('api/year_ranges/<int:sub_model_id>/', views.get_year_ranges, name='get_year_ranges'),
    path('export_complaints/', views.export_complaints, name='export_complaints'),
    path('upload-cars/', views.upload_car_csv, name='upload_car_csv'),
    path('add-sku/', views.add_sku, name='add_sku'),
    path('delete-sku/<int:sku_id>/', views.delete_sku, name='delete_sku'),
    path('edit-sku/<int:sku_id>/', views.edit_sku, name='edit_sku'),
    path('admin_panel/', views.admin_panel_view, name='admin_panel'),
    path('admin-panel/edit-group/', views.edit_group, name='edit_group'),
    path('admin-panel/delete-group/', views.delete_group, name='delete_group'),
    path('admin-panel/edit-user/', views.edit_user, name='edit_user'),
    path('admin-panel/delete-user/', views.delete_user, name='delete_user'),

    


        

]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
