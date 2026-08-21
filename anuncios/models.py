from datetime import timedelta
from io import BytesIO
import os

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from PIL import Image
from django.db.models import Manager


# Función auxiliar para convertir cualquier imagen a WebP
def optimizar_e_convertir_webp(campo_imagen):
    if not campo_imagen:
        return campo_imagen

    # Abrir la imagen subida con Pillow
    img = Image.open(campo_imagen)

    # Convertir imágenes con transparencias (PNG/RGBA) a RGB para evitar errores
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    output = BytesIO()
    # Comprimir al 80% de calidad y optimizar
    img.save(output, format="WEBP", quality=80, optimize=True)
    output.seek(0)

    # Cambiar la extensión del archivo a .webp
    nombre_base = os.path.splitext(campo_imagen.name)[0]
    nuevo_nombre = f"{nombre_base}.webp"

    return ContentFile(output.read(), name=nuevo_nombre)


# 1. CATEGORÍA
class Categoria(models.Model):
    nombre = models.CharField(
        max_length=100, verbose_name="Nombre de la Categoría"
    )
    slug = models.SlugField(unique=True, null=True, blank=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"

    def __str__(self):
        return self.nombre


# --- CUSTOM MANAGER PARA FILTRAR EN LA VISTA DE INICIO ---
class AnuncioActivoManager(models.Manager):
    def vigentes(self):
        """Retorna únicamente los anuncios pagados cuya fecha de vencimiento no ha expirado."""
        ahora = timezone.now()
        return (
            self.filter(
                pagado=True, fecha_pago__isnull=False
            ).extra(
                where=["fecha_pago + (dias_duracion || ' days')::interval > %s"],
                params=[ahora],
            )
            if self.model._meta.database.startswith("post")
            else [
                a
                for a in self.filter(pagado=True, fecha_pago__isnull=False)
                if a.esta_vigente
            ]
        )


# 2. ANUNCIO
class Anuncio(models.Model):
    # --- AYUDA DE TIPO PARA PYLANCE EN VS CODE ---
    imagenes_adicionales: Manager["ImagenAnuncio"]

    # Tus campos actuales...
    titulo = models.CharField(
        max_length=200, verbose_name="Título del Anuncio"
    )
    descripcion = models.TextField(verbose_name="Descripción")
    precio = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Precio"
    )
    imagen = models.ImageField(
        upload_to="anuncios_fotos/",
        null=True,
        blank=True,
        verbose_name="Imagen Principal",
    )
    fecha_publicacion = models.DateTimeField(
        auto_now_add=True, verbose_name="Fecha de Creación"
    )

    # Campos de contacto directo
    whatsapp = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="Número de WhatsApp",
        help_text="Ejemplo: 573000000000",
    )
    telegram = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Usuario de Telegram",
        help_text="Ejemplo: TuUsuarioTelegram (sin @)",
    )

    # Sistema de Cobro y Tiempo de Publicación
    pagado = models.BooleanField(default=False, verbose_name="¿Está Pagado?")
    fecha_pago = models.DateTimeField(
        null=True, blank=True, verbose_name="Fecha y Hora de Pago"
    )
    dias_duracion = models.IntegerField(
        default=30, verbose_name="Días de Duración"
    )

    # Relaciones de la base de datos
    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, verbose_name="Anunciante"
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="anuncios",
        verbose_name="Categoría",
    )

    # Managers
    objects = models.Manager()
    publicados = AnuncioActivoManager()

    class Meta:
        verbose_name = "Anuncio"
        verbose_name_plural = "Anuncios"
        ordering = ["-fecha_publicacion"]

    def __str__(self):
        return self.titulo

    # --- OPTIMIZACIÓN Y CONVERSIÓN A WEBP ---
    def save(self, *args, **kwargs):
        if self.imagen and not self.imagen.name.endswith(".webp"):
            self.imagen = optimizar_e_convertir_webp(self.imagen)
        super().save(*args, **kwargs)

    # --- CÁLCULOS DINÁMICOS DE TIEMPO Y VIGENCIA ---
    @property
    def fecha_vencimiento(self):
        if self.fecha_pago:
            return self.fecha_pago + timedelta(days=self.dias_duracion)
        return None
    
    @property
    def esta_vigente(self) -> bool:
        if not self.pagado or self.fecha_pago is None:
            return False

        fecha_vencimiento = self.fecha_vencimiento

        if fecha_vencimiento is None:
            return False

        return timezone.now() < fecha_vencimiento

    @property
    def tiempo_publicado(self):
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
    def tiempo_restante(self) -> str:
        if not self.esta_vigente:
            return "Vencido / Inactivo"

        fecha_vencimiento = self.fecha_vencimiento

        if fecha_vencimiento is None:
            return "Vencido / Inactivo"

        restante = fecha_vencimiento - timezone.now()
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
    anuncio = models.ForeignKey(
        Anuncio,
        on_delete=models.CASCADE,
        related_name="imagenes_adicionales",
    )
    imagen = models.ImageField(upload_to="anuncios_fotos/")

    class Meta:
        verbose_name = "Imagen Adicional"
        verbose_name_plural = "Imágenes Adicionales"

    def __str__(self):
        return f"Foto adicional de {self.anuncio.titulo}"

    def save(self, *args, **kwargs):
        if self.imagen and not self.imagen.name.endswith(".webp"):
            self.imagen = optimizar_e_convertir_webp(self.imagen)
        super().save(*args, **kwargs)