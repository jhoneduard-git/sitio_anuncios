import hashlib
import re
import uuid

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
import requests
from .models import Anuncio, Categoria, ImagenAnuncio
import requests

# funcion para obtener la IP del cliente saber si es local o extranjero, para mostrar el precio en pesos o dolares
def obtener_ip_cliente(request):
    """Obtiene la IP pública del cliente para detectar su país."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip

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
    anuncio_encontrado = get_object_or_404(Anuncio, id=id)
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
        titulo = request.POST.get("titulo")
        descripcion = request.POST.get("descripcion")
        precio = request.POST.get("precio")
        categoria_id = request.POST.get("categoria")
        imagen = request.FILES.get("imagen")

        whatsapp = request.POST.get("whatsapp", "").strip()
        telegram = request.POST.get("telegram", "").strip()

        categoria = get_object_or_404(Categoria, id=categoria_id)

        nuevo_anuncio = Anuncio.objects.create(
            titulo=titulo,
            descripcion=descripcion,
            precio=precio,
            categoria=categoria,
            imagen=imagen,
            whatsapp=whatsapp,
            telegram=telegram,
            usuario=request.user,
            pagado=False,
        )

        fotos_adicionales = request.FILES.getlist("imagenes_adicionales")
        for foto in fotos_adicionales:
            ImagenAnuncio.objects.create(anuncio=nuevo_anuncio, imagen=foto)

        return redirect("pasarela_pago", anuncio_id=nuevo_anuncio.id)

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
    anuncio = get_object_or_404(Anuncio, id=anuncio_id, usuario=request.user)

    # 1. Detectar ubicación por IP
    ip_cliente = obtener_ip_cliente(request)
    pais_codigo = "CO"  # Por defecto Colombia

    try:
        res = requests.get(
            f"http://ip-api.com/json/{ip_cliente}?fields=countryCode",
            timeout=3,
        )
        if res.status_code == 200:
            pais_codigo = res.json().get("countryCode", "CO")
    except requests.RequestException:
        pass

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
        f"ANUNCIO-{anuncio.id}-{anuncio.usuario.id}-{codigo_unico}"
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
    id_transaccion = request.GET.get("id") or request.GET.get("transaction_id")

    if not id_transaccion:
        messages.error(
            request, "No se recibió el código de transacción de Wompi."
        )
        return redirect("mis_anuncios")

    pub_key = str(getattr(settings, "WOMPI_PUBLIC_KEY", "")).strip()
    base_url = (
        "https://checkout.wompi.co/v1"
        if pub_key.startswith("pub_prod_")
        else "https://sandbox.wompi.co/v1"
    )

    url_wompi = f"{base_url}/transactions/{id_transaccion}"

    try:
        response = requests.get(url_wompi, timeout=10)

        if response.status_code == 200:
            data = response.json().get("data", {})
            estado = data.get("status")
            referencia = data.get("reference", "")

            # Extracción segura del ID con Expresión Regular
            match = re.search(r"ANUNCIO-(\d+)", referencia)
            if not match:
                messages.error(
                    request,
                    "La referencia de pago recibida no tiene un formato válido.",
                )
                return redirect("mis_anuncios")

            anuncio_id = match.group(1)

            try:
                anuncio = Anuncio.objects.get(id=anuncio_id)
            except Anuncio.DoesNotExist:
                messages.error(
                    request,
                    "No se encontró el anuncio asociado a este pago.",
                )
                return redirect("mis_anuncios")

            # Actualización atómica en base de datos al aprobar el pago
            if estado == "APPROVED":
                with transaction.atomic():
                    anuncio.pagado = True
                    anuncio.fecha_pago = timezone.now()
                    anuncio.save()

                messages.success(
                    request,
                    f"¡Pago aprobado con éxito! Tu anuncio '{anuncio.titulo}' ya está publicado.",
                )
            elif estado == "PENDING":
                messages.info(
                    request,
                    "El pago está en proceso de verificación por la entidad bancaria.",
                )
            else:
                messages.warning(
                    request, f"El pago no se pudo completar. Estado: {estado}"
                )

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
        "-id"
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
        Anuncio, id=id, usuario=request.user, pagado=True
    )

    if request.method == "POST":
        anuncio.titulo = request.POST.get("titulo")
        anuncio.descripcion = request.POST.get("descripcion")
        anuncio.precio = request.POST.get("precio")
        anuncio.whatsapp = request.POST.get("whatsapp", "").strip()
        anuncio.telegram = request.POST.get("telegram", "").strip()

        categoria_id = request.POST.get("categoria")
        if categoria_id:
            anuncio.categoria = get_object_or_404(Categoria, id=categoria_id)

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
        ImagenAnuncio, id=foto_id, anuncio__usuario=request.user
    )
    anuncio_id = foto.anuncio.id
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