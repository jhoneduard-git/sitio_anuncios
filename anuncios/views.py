import hashlib
import re
import uuid

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from .models import Anuncio, Categoria, ImagenAnuncio

# funcion para obtener la IP del cliente saber si es local o extranjero, para mostrar el precio en pesos o dolares
def obtener_ip_cliente(request):
    """Obtiene la IP pública del cliente para detectar su país."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def obtener_pais_por_ip(ip_cliente):
    """Obtiene el código de país usando una conexión HTTPS."""
    try:
        respuesta = requests.get(
            f"https://ipapi.co/{ip_cliente}/json/",
            timeout=3,
        )
        if respuesta.status_code == 200:
            return respuesta.json().get("country_code", "CO")
    except (requests.RequestException, ValueError):
        pass
    return "CO"


def validar_firma_wompi(data):
    """Valida la firma de integridad de una transacción de Wompi."""
    checksum_recibido = (
        data.get("signature", {}).get("checksum")
        or data.get("checksum")
    )
    integrity_secret = str(
        getattr(settings, "WOMPI_INTEGRITY_SECRET", "")
    ).strip()

    if not checksum_recibido or not integrity_secret:
        return True

    cadena_local = (
        f"{data.get('reference', '')}"
        f"{data.get('amount_in_cents')}"
        f"{data.get('currency')}"
        f"{integrity_secret}"
    )
    checksum_calculado = hashlib.sha256(
        cadena_local.encode("utf-8")
    ).hexdigest()
    return checksum_calculado.lower() == str(checksum_recibido).lower()


def obtener_anuncio_de_referencia(referencia):
    """Extrae el anuncio asociado a una referencia de pago."""
    match = re.search(r"ANUNCIO-(\d+)", referencia)
    if not match:
        return None

    try:
        return Anuncio.objects.get(pk=match.group(1))
    except Anuncio.DoesNotExist:
        return None


def procesar_estado_pago(anuncio, estado):
    """Actualiza el anuncio y devuelve el nivel y mensaje para Django."""
    if estado == "APPROVED":
        if anuncio.pagado:
            return "info", f"El anuncio '{anuncio.titulo}' ya se encuentra activo."

        with transaction.atomic():
            anuncio.pagado = True
            anuncio.fecha_pago = timezone.now()
            anuncio.save(update_fields=["pagado", "fecha_pago"])
        return (
            "success",
            f"¡Pago aprobado con éxito! Tu anuncio '{anuncio.titulo}' ya está publicado.",
        )

    if estado == "PENDING":
        return (
            "info",
            "El pago está en proceso de verificación por la entidad bancaria.",
        )

    return "warning", f"El pago no se pudo completar. Estado: {estado}"


def agregar_mensaje_pago(request, nivel, mensaje):
    getattr(messages, nivel)(request, mensaje)


def crear_anuncio_desde_request(request):
    """Crea un anuncio y sus imágenes adicionales desde un formulario POST."""
    categoria = get_object_or_404(
        Categoria,
        pk=request.POST.get("categoria"),
    )
    anuncio = Anuncio.objects.create(
        titulo=request.POST.get("titulo"),
        descripcion=request.POST.get("descripcion"),
        precio=request.POST.get("precio"),
        categoria=categoria,
        imagen=request.FILES.get("imagen"),
        whatsapp=request.POST.get("whatsapp", "").strip(),
        telegram=request.POST.get("telegram", "").strip(),
        usuario=request.user,
        pagado=False,
    )

    for foto in request.FILES.getlist("imagenes_adicionales"):
        ImagenAnuncio.objects.create(anuncio=anuncio, imagen=foto)
    return anuncio

# ==============================================================================
# 1. PÁGINA DE INICIO (Solo GET)
# ==============================================================================
@require_GET
def pagina_inicio(request):
    # Consulta optimizada: solo anuncios pagados y con fecha de pago registrada
    anuncios_base = Anuncio.objects.filter(
        pagado=True, fecha_pago__isnull=False
    ).order_by("-fecha_pago")

    buscar_texto = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "").strip()

    if buscar_texto:
        filtro = (
            Q(titulo__icontains=buscar_texto)
            | Q(descripcion__icontains=buscar_texto)
            | Q(categoria__nombre__icontains=buscar_texto)
        )

        try:
            precio_val = float(buscar_texto)
            filtro |= Q(precio__lte=precio_val)
        except ValueError:
            pass

        anuncios_base = anuncios_base.filter(filtro)

    if categoria_id:
        anuncios_base = anuncios_base.filter(categoria_id=categoria_id)

    # Filtrado dinámico por la propiedad 'esta_vigente'
    anuncios_activos = [
        anuncio for anuncio in anuncios_base if anuncio.esta_vigente
    ]
    categorias = Categoria.objects.all()

    contexto = {
        "anuncios": anuncios_activos,
        "categorias": categorias,
        "buscar_texto": buscar_texto,
        "categoria_id": categoria_id,
    }
    return render(request, "anuncios/inicio.html", contexto)


# ==============================================================================
# 2. DETALLE DE ANUNCIO (Solo GET)
# ==============================================================================
@require_GET
def detalle_anuncio(request, id):
    anuncio_encontrado = get_object_or_404(Anuncio, pk=id)
    fotos_adicionales = anuncio_encontrado.imagenes_adicionales.all()

    contexto = {
        "anuncio": anuncio_encontrado,
        "fotos_adicionales": fotos_adicionales,
    }
    return render(request, "anuncios/detalle.html", contexto)


# ==============================================================================
# 3. CREAR ANUNCIO (GET / POST)
# ==============================================================================
@login_required
@require_http_methods(["GET", "POST"])
def crear_anuncio(request):
    if request.method == "POST":
        anuncio = crear_anuncio_desde_request(request)
        return redirect("pasarela_pago", anuncio_id=anuncio.pk)

    categorias = Categoria.objects.all()
    return render(
        request, "anuncios/crear_anuncio.html", {"categorias": categorias}
    )


# ==============================================================================
# 4. PASARELA DE PAGO WOMPI (Solo GET)
# ==============================================================================
@login_required
@require_GET
def pasarela_pago(request, anuncio_id):
    anuncio = get_object_or_404(Anuncio, pk=anuncio_id, usuario=request.user)

    # 1. Detectar ubicación por IP
    ip_cliente = obtener_ip_cliente(request)
    pais_codigo = obtener_pais_por_ip(ip_cliente)

    # 2. Asignar tarifa según el país (Siempre en COP)
    if pais_codigo == "CO":
        monto_cop = 100000  # Tarifa nacional
    else:
        monto_cop = 300000  # Tarifa internacional

    monto_centavos = int(monto_cop * 100)
    moneda = "COP"

    # 3. Referencia única de pago
    codigo_unico = uuid.uuid4().hex[:6]
    referencia_pago = (
        f"ANUNCIO-{anuncio.pk}-{anuncio.usuario.pk}-{codigo_unico}"
    )

    # 4. Firmado SHA-256 de Wompi
    wompi_public_key = str(getattr(settings, "WOMPI_PUBLIC_KEY", "")).strip()
    secreto_integridad = str(
        getattr(settings, "WOMPI_INTEGRITY_SECRET", "")
    ).strip()

    cadena_a_encriptar = (
        f"{referencia_pago}{monto_centavos}{moneda}{secreto_integridad}"
    )
    firma_integridad = hashlib.sha256(
        cadena_a_encriptar.encode("utf-8")
    ).hexdigest()

    redirect_url = request.build_absolute_uri(reverse("respuesta_pago"))

    contexto = {
        "anuncio": anuncio,
        "monto_cop": monto_cop,
        "monto_centavos": monto_centavos,
        "moneda": moneda,
        "referencia_pago": referencia_pago,
        "wompi_public_key": wompi_public_key,
        "firma_integridad": firma_integridad,
        "redirect_url": redirect_url,
    }
    return render(request, "anuncios/pasarela_pago.html", contexto)
# ==============================================================================
# 5. RESPUESTA Y CONFIRMACIÓN DE PAGO WOMPI (Solo GET)
# ==============================================================================
@require_GET
def respuesta_pago(request):
    id_transaccion = request.GET.get("id") or request.GET.get(
        "transaction_id"
    )

    if not id_transaccion:
        messages.error(
            request, "No se recibió el código de transacción de Wompi."
        )
        return redirect("mis_anuncios")

    pub_key = str(getattr(settings, "WOMPI_PUBLIC_KEY", "")).strip()
    base_url = (
        "https://production.wompi.co/v1"
        if pub_key.startswith("pub_prod_")
        else "https://sandbox.wompi.co/v1"
    )

    url_wompi = f"{base_url}/transactions/{id_transaccion}"

    try:
        response = requests.get(url_wompi, timeout=10)

        if response.status_code == 200:
            data = response.json().get("data", {})
            estado = data.get("status")
            if not validar_firma_wompi(data):
                messages.error(
                    request,
                    "Violación de integridad: La firma de la transacción no coincide.",
                )
                return redirect("mis_anuncios")

            anuncio = obtener_anuncio_de_referencia(data.get("reference", ""))
            if anuncio is None:
                messages.error(
                    request,
                    "No se encontró el anuncio asociado a este pago.",
                )
                return redirect("mis_anuncios")

            nivel, mensaje = procesar_estado_pago(anuncio, estado)
            agregar_mensaje_pago(request, nivel, mensaje)

            return render(
                request,
                "anuncios/respuesta_pago.html",
                {"estado": estado, "anuncio": anuncio, "transaccion": data},
            )

    except requests.RequestException:
        messages.error(
            request, "Ocurrió un error al verificar la transacción con Wompi."
        )

    return redirect("mis_anuncios")
          
# ==============================================================================
# 6. REGISTRO DE USUARIOS (GET / POST)
# ==============================================================================
@require_http_methods(["GET", "POST"])
def registrar_usuario(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            login(request, usuario)
            return redirect("inicio")
    else:
        form = UserCreationForm()

    return render(request, "anuncios/registro.html", {"form": form})


# ==============================================================================
# 7. PANEL 'MIS ANUNCIOS' (Solo GET)
# ==============================================================================
@login_required
@require_GET
def mis_anuncios(request):
    anuncios_usuario = Anuncio.objects.filter(usuario=request.user).order_by(
        "-pk"
    )
    return render(
        request, "anuncios/mis_anuncios.html", {"anuncios": anuncios_usuario}
    )


# ==============================================================================
# 8. EDITAR ANUNCIO PAGADO (GET / POST)
# ==============================================================================
@login_required
@require_http_methods(["GET", "POST"])
def editar_anuncio(request, id):
    anuncio = get_object_or_404(
        Anuncio, pk=id, usuario=request.user, pagado=True
    )

    if request.method == "POST":
        anuncio.titulo = request.POST.get("titulo")
        anuncio.descripcion = request.POST.get("descripcion")
        anuncio.precio = request.POST.get("precio")
        anuncio.whatsapp = request.POST.get("whatsapp", "").strip()
        anuncio.telegram = request.POST.get("telegram", "").strip()

        categoria_id = request.POST.get("categoria")
        if categoria_id:
            anuncio.categoria = get_object_or_404(Categoria, pk=categoria_id)

        if request.FILES.get("imagen"):
            anuncio.imagen = request.FILES.get("imagen")

        anuncio.save()

        fotos_nuevas = request.FILES.getlist("imagenes_adicionales")
        for foto in fotos_nuevas:
            ImagenAnuncio.objects.create(anuncio=anuncio, imagen=foto)

        return redirect("mis_anuncios")

    categorias = Categoria.objects.all()
    fotos_adicionales = anuncio.imagenes_adicionales.all()

    contexto = {
        "anuncio": anuncio,
        "categorias": categorias,
        "fotos_adicionales": fotos_adicionales,
    }
    return render(request, "anuncios/editar_anuncio.html", contexto)


# ==============================================================================
# 9. ELIMINAR FOTO ADICIONAL (Exclusivamente POST)
# ==============================================================================
@login_required
@require_POST
def eliminar_foto(request, foto_id):
    foto = get_object_or_404(
        ImagenAnuncio, pk=foto_id, anuncio__usuario=request.user
    )
    anuncio_id = foto.anuncio.pk
    foto.delete()
    return redirect("editar_anuncio", id=anuncio_id)

# ==============================================================================
# 10. POLÍTICAS DE PRIVACIDAD esto conecta las plantillas con django y permite que se muestren en la web
# ==============================================================================

@require_GET
def normas_uso(request):
    return render(request, "anuncios/normas_uso.html")


@require_GET
def politicas_privacidad(request):
    return render(request, "anuncios/politicas_privacidad.html")