from django.urls import path
from . import views



urlpatterns = [
    # Login/Logout
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Profile (Optional)
    path('profile/', views.profile_view, name='profile'),
]