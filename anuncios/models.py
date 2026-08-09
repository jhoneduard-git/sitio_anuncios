from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

# 1. CATEGORÍA
class Categoria(models.Model):
    nombre = models.CharField(max_length=100, verbose_name="Nombre de la Categoría")
    slug = models.SlugField(unique=True, null=True, blank=True)

    def __str__(self):
        return self.nombre


# 2. ANUNCIO (Con control de tiempo, vigencia y contactos)
class Anuncio(models.Model):
    titulo = models.CharField(max_length=200, verbose_name="Título del Anuncio")
    descripcion = models.TextField(verbose_name="Descripción")
    precio = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio")
    imagen = models.ImageField(upload_to='anuncios_fotos/', null=True, blank=True, verbose_name="Imagen Principal")
    fecha_publicacion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    
    # 🆕 Campos de contacto directo (WhatsApp y Telegram)
    whatsapp = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        verbose_name="Número de WhatsApp",
        help_text="Ejemplo: 573000000000"
    )
    telegram = models.CharField(
        max_length=50, 
        blank=True, 
        null=True, 
        verbose_name="Usuario de Telegram",
        help_text="Ejemplo: TuUsuarioTelegram (sin @)"
    )

    # Sistema de Cobro y Tiempo de Publicación
    pagado = models.BooleanField(default=False, verbose_name="¿Está Pagado?")
    fecha_pago = models.DateTimeField(null=True, blank=True, verbose_name="Fecha y Hora de Pago")
    dias_duracion = models.IntegerField(default=30, verbose_name="Días de Duración")
    
    # Relaciones de la base de datos
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Anunciante")
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='anuncios', verbose_name="Categoría")

    def __str__(self):
        return self.titulo

    # --- CÁLCULOS DINÁMICOS DE TIEMPO Y VIGENCIA ---

    @property
    def fecha_vencimiento(self):
        """Calcula la fecha y hora exactas en que expira el anuncio."""
        if self.fecha_pago:
            return self.fecha_pago + timedelta(days=self.dias_duracion)
        return None

    @property
    def esta_vigente(self):
        """Verifica si el anuncio está pagado y si aún no ha alcanzado la fecha de vencimiento."""
        if not self.pagado or not self.fecha_pago:
            return False
        return timezone.now() < self.fecha_vencimiento

    @property
    def tiempo_publicado(self):
        """Retorna cuánto tiempo lleva publicado en lenguaje natural (ej: '3 días' o '5 horas')."""
        if not self.fecha_pago:
            return "No publicado"
        
        transcurrido = timezone.now() - self.fecha_pago
        dias = transcurrido.days
        if dias > 0:
            return f"{dias} día{'s' if dias > 1 else ''}"
        
        horas = transcurrido.seconds // 3600
        if horas > 0:
            return f"{horas} hora{'s' if horas > 1 else ''}"
            
        minutos = transcurrido.seconds // 60
        return f"{minutos} min"

    @property
    def tiempo_restante(self):
        """Retorna cuánto tiempo le queda disponible al anuncio."""
        if not self.esta_vigente:
            return "Vencido / Inactivo"
        
        restante = self.fecha_vencimiento - timezone.now()
        dias = restante.days
        if dias > 0:
            return f"{dias} día{'s' if dias > 1 else ''}"
        
        horas = restante.seconds // 3600
        if horas > 0:
            return f"{horas} hora{'s' if horas > 1 else ''}"
            
        minutos = restante.seconds // 60
        return f"{minutos} min"


# 3. IMÁGENES ADICIONALES
class ImagenAnuncio(models.Model):
    anuncio = models.ForeignKey(Anuncio, on_delete=models.CASCADE, related_name='imagenes_adicionales')
    imagen = models.ImageField(upload_to='anuncios_fotos/')

    def __str__(self):
        return f"Foto adicional de {self.anuncio.titulo}"