import hashlib
import requests
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.utils import timezone
from django.contrib import messages
from django.conf import settings
from .models import Anuncio, Categoria, ImagenAnuncio


# 1. PÁGINA DE INICIO (Solo GET)
@require_GET
def pagina_inicio(request):
    anuncios_base = Anuncio.objects.filter(
        pagado=True, 
        fecha_pago__isnull=False
    ).order_by('-fecha_pago')

    buscar_texto = request.GET.get('q', '').strip()
    categoria_id = request.GET.get('categoria', '').strip()

    if buscar_texto:
        filtro = (
            Q(titulo__icontains=buscar_texto) | 
            Q(descripcion__icontains=buscar_texto) |
            Q(categoria__nombre__icontains=buscar_texto)
        )
        
        try:
            precio_val = float(buscar_texto)
            filtro |= Q(precio__lte=precio_val)
        except ValueError:
            pass

        anuncios_base = anuncios_base.filter(filtro)

    if categoria_id:
        anuncios_base = anuncios_base.filter(categoria_id=categoria_id)

    anuncios_activos = [anuncio for anuncio in anuncios_base if anuncio.esta_vigente]
    categorias = Categoria.objects.all() 

    contexto = {
        'anuncios': anuncios_activos,
        'categorias': categorias,
        'buscar_texto': buscar_texto,
        'categoria_id': categoria_id,
    }
    return render(request, 'anuncios/inicio.html', contexto)


# 2. DETALLE DE ANUNCIO (Solo GET)
@require_GET
def detalle_anuncio(request, id):
    anuncio_encontrado = get_object_or_404(Anuncio, id=id)
    fotos_adicionales = anuncio_encontrado.imagenes_adicionales.all()
    
    contexto = {
        'anuncio': anuncio_encontrado,
        'fotos_adicionales': fotos_adicionales
    }
    return render(request, 'anuncios/detalle.html', contexto)


# 3. CREAR ANUNCIO (GET / POST)
@login_required
@require_http_methods(["GET", "POST"])
def crear_anuncio(request):
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        descripcion = request.POST.get('descripcion')
        precio = request.POST.get('precio')
        categoria_id = request.POST.get('categoria')
        imagen = request.FILES.get('imagen')
        
        whatsapp = request.POST.get('whatsapp', '').strip()
        telegram = request.POST.get('telegram', '').strip()

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
            pagado=False
        )

        fotos_adicionales = request.FILES.getlist('imagenes_adicionales')
        for foto in fotos_adicionales:
            ImagenAnuncio.objects.create(anuncio=nuevo_anuncio, imagen=foto)
        
        return redirect('pasarela_pago', anuncio_id=nuevo_anuncio.id)

    categorias = Categoria.objects.all()
    return render(request, 'anuncios/crear_anuncio.html', {'categorias': categorias})


# 4. PASARELA DE PAGO (Limpia espacios y calcula la firma SHA-256)
@login_required
@require_GET
def pasarela_pago(request, anuncio_id):
    anuncio = get_object_or_404(Anuncio, id=anuncio_id, usuario=request.user)
    
    monto_cop = 5000 
    monto_centavos = int(monto_cop * 100)
    moneda = "COP"  # Strictamente en mayúsculas
    referencia_pago = f"ANUNCIO-{anuncio.id}-{anuncio.usuario.id}"
    
    # 🔑 Llave pública sin espacios alrededor
    wompi_public_key = str(getattr(settings, 'WOMPI_PUBLIC_KEY', '')).strip()
    
    # 🔒 Secreto de Integridad sin espacios alrededor
    secreto_integridad = str(getattr(settings, 'WOMPI_INTEGRITY_SECRET', '')).strip()
    
    # 🔗 Concatenación estricta de Wompi: Referencia + MontoEnCentavos + Moneda + Secreto
    cadena_a_encriptar = f"{referencia_pago}{monto_centavos}{moneda}{secreto_integridad}"
    
    # Generar Hash SHA-256
    firma_integridad = hashlib.sha256(cadena_a_encriptar.encode('utf-8')).hexdigest()

    contexto = {
        'anuncio': anuncio,
        'monto_cop': monto_cop,
        'monto_centavos': monto_centavos,
        'referencia_pago': referencia_pago,
        'wompi_public_key': wompi_public_key,
        'firma_integridad': firma_integridad,
    }
    return render(request, 'anuncios/pasarela_pago.html', contexto)


# 5. RESPUESTA Y CONFIRMACIÓN DE PAGO WOMPI (Solo GET)
@require_GET
def respuesta_pago(request):
    id_transaccion = request.GET.get('id')
    
    if not id_transaccion:
        messages.error(request, "No se proporcionó ningún ID de transacción.")
        return redirect('mis_anuncios')
        
    pub_key = getattr(settings, 'WOMPI_PUBLIC_KEY', '')
    base_url = "https://checkout.wompi.co/v1" if pub_key.startswith("pub_prod_") else "https://sandbox.wompi.co/v1"
    
    url_wompi = f"{base_url}/transactions/{id_transaccion}"
    
    try:
        response = requests.get(url_wompi, timeout=10)
        if response.status_code == 200:
            data = response.json().get('data', {})
            estado = data.get('status')
            referencia = data.get('reference')
            
            try:
                anuncio_id = referencia.split('-')[1]
                anuncio = Anuncio.objects.get(id=anuncio_id)
            except (IndexError, ValueError, Anuncio.DoesNotExist):
                messages.error(request, "No se encontró el anuncio correspondiente al pago.")
                return redirect('mis_anuncios')

            if estado == 'APPROVED':
                if not anuncio.pagado:
                    anuncio.pagado = True
                    anuncio.fecha_pago = timezone.now()
                    anuncio.save()
                messages.success(request, f"¡Pago aprobado con éxito! Tu anuncio '{anuncio.titulo}' ha sido publicado.")
            else:
                messages.warning(request, f"El pago no fue completado. Estado: {estado}")

            return render(request, 'anuncios/respuesta_pago.html', {
                'estado': estado,
                'anuncio': anuncio,
                'transaccion': data
            })
            
    except requests.RequestException:
        messages.error(request, "Ocurrió un error al verificar la transacción con Wompi.")
        
    return redirect('mis_anuncios')


# 6. REGISTRO DE USUARIOS (GET / POST)
@require_http_methods(["GET", "POST"])
def registrar_usuario(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            login(request, usuario)
            return redirect('inicio')
    else:
        form = UserCreationForm()
    
    return render(request, 'anuncios/registro.html', {'form': form})


# 7. PANEL 'MIS ANUNCIOS' (Solo GET)
@login_required
@require_GET
def mis_anuncios(request):
    anuncios_usuario = Anuncio.objects.filter(usuario=request.user).order_by('-id')
    return render(request, 'anuncios/mis_anuncios.html', {'anuncios': anuncios_usuario})


# 8. EDITAR ANUNCIO PAGADO (GET / POST)
@login_required
@require_http_methods(["GET", "POST"])
def editar_anuncio(request, id):
    anuncio = get_object_or_404(Anuncio, id=id, usuario=request.user, pagado=True)

    if request.method == 'POST':
        anuncio.titulo = request.POST.get('titulo')
        anuncio.descripcion = request.POST.get('descripcion')
        anuncio.precio = request.POST.get('precio')
        anuncio.whatsapp = request.POST.get('whatsapp', '').strip()
        anuncio.telegram = request.POST.get('telegram', '').strip()
        
        categoria_id = request.POST.get('categoria')
        if categoria_id:
            anuncio.categoria = get_object_or_404(Categoria, id=categoria_id)

        if request.FILES.get('imagen'):
            anuncio.imagen = request.FILES.get('imagen')

        anuncio.save()

        fotos_nuevas = request.FILES.getlist('imagenes_adicionales')
        for foto in fotos_nuevas:
            ImagenAnuncio.objects.create(anuncio=anuncio, imagen=foto)

        return redirect('mis_anuncios')

    categorias = Categoria.objects.all()
    fotos_adicionales = anuncio.imagenes_adicionales.all()

    contexto = {
        'anuncio': anuncio,
        'categorias': categorias,
        'fotos_adicionales': fotos_adicionales
    }
    return render(request, 'anuncios/editar_anuncio.html', contexto)


# 9. ELIMINAR FOTO ADICIONAL (Exclusivamente POST)
@login_required
@require_POST
def eliminar_foto(request, foto_id):
    foto = get_object_or_404(ImagenAnuncio, id=foto_id, anuncio__usuario=request.user)
    anuncio_id = foto.anuncio.id
    foto.delete()
    return redirect('editar_anuncio', id=anuncio_id)