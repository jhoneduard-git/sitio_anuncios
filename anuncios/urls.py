from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    # Rutas de navegación de anuncios
    path("", views.pagina_inicio, name="inicio"),
    path("anuncio/<int:id>/", views.detalle_anuncio, name="detalle_anuncio"),
    path("crear/", views.crear_anuncio, name="crear_anuncio"),
    # Panel de gestión del usuario
    path("mis-anuncios/", views.mis_anuncios, name="mis_anuncios"),
    path(
        "mis-anuncios/editar/<int:id>/",
        views.editar_anuncio,
        name="editar_anuncio",
    ),
    path(
        "mis-anuncios/eliminar-foto/<int:foto_id>/",
        views.eliminar_foto,
        name="eliminar_foto",
    ),
    # Rutas del sistema de cobro / pasarela Wompi
    path("pago/<int:anuncio_id>/", views.pasarela_pago, name="pasarela_pago"),
    path(
        "respuesta-pago/", views.respuesta_pago, name="respuesta_pago"
    ),  # 👈 OBLIGATORIA PARA WOMPI
    # Rutas de información legal y cumplimiento
    path("normas-de-uso/", views.normas_uso, name="normas_uso"),
    path(
        "politicas-de-privacidad/",
        views.politicas_privacidad,
        name="politicas_privacidad",
    ),
    # Rutas del sistema de autenticación de usuarios
    path("registro/", views.registrar_usuario, name="registro"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="anuncios/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]