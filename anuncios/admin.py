from django.contrib import admin
from .models import Anuncio, Categoria, ImagenAnuncio

# 1. Configuración para subir fotos adicionales en el mismo formulario del Anuncio
class ImagenAnuncioInline(admin.TabularInline):
    model = ImagenAnuncio
    extra = 3 # Muestra 3 casillas vacías por defecto

# 2. Registro del modelo Anuncio con su galería de imágenes incorporada
@admin.register(Anuncio)
class AnuncioAdmin(admin.ModelAdmin):
    inlines = [ImagenAnuncioInline]

# 3. Registro de las Categorías (Solo una vez para evitar errores)
admin.site.register(Categoria)