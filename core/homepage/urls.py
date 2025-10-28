from django.urls import path

from core.homepage.views import homepage, login

# creo las rutas de la app homepage para poder llamarla en urls.py de config
# aqui llamo a la vista homepage configurada en views.py de la app homepage
urlpatterns = [
    path('1/', homepage),
    path('2/', login),
]
