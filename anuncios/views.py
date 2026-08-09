import requests
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages
from django.conf import settings
from .models import Anuncio, Categoria, ImagenAnuncio


# 1. VISTA DE LA PÁGINA DE INICIO (Con Búsqueda Multipropósito y Vigencia)
def pagina_inicio(request):
    # Traemos anuncios que estén marcados como pagados y tengan fecha de pago
    anuncios_base = Anuncio.objects.filter(
        pagado=True, 
        fecha_pago__isnull=False
    ).order_by('-fecha_pago')

    buscar_texto = request.GET.get('q', '').strip()
    categoria_id = request.GET.get('categoria', '').strip()

    # 🔍 BÚSQUEDA MULTIPROPÓSITO (Título, Descripción, Categoría y Precio)
    if buscar_texto:
        filtro = (
            Q(titulo__icontains=buscar_texto) | 
            Q(descripcion__icontains=buscar_texto) |
            Q(categoria__nombre__icontains=buscar_texto)
        )
        
        # Si el usuario ingresó un número, buscamos precios menores o iguales
        try:
            precio_val = float(buscar_texto)
            filtro |= Q(precio__lte=precio_val)
        except ValueError:
            pass  # No era un número, ignoramos el filtro de precio

        anuncios_base = anuncios_base.filter(filtro)

    # 🏷️ Filtro por selector de Categoría
    if categoria_id:
        anuncios_base = anuncios_base.filter(categoria_id=categoria_id)

    # ⏱️ Filtro de vigencia en memoria
    anuncios_activos = [anuncio for anuncio in anuncios_base if anuncio.esta_vigente]

    categorias = Categoria.objects.all() 

    contexto = {
        'anuncios': anuncios_activos,
        'categorias': categorias,
        'buscar_texto': buscar_texto,
        'categoria_id': categoria_id,
    }
    return render(request, 'anuncios/inicio.html', contexto)


# 2. VISTA DE DETALLE DEL ANUNCIO
def detalle_anuncio(request, id):
    anuncio_encontrado = get_object_or_404(Anuncio, id=id)
    fotos_adicionales = anuncio_encontrado.imagenes_adicionales.all()
    
    contexto = {
        'anuncio': anuncio_encontrado,
        'fotos_adicionales': fotos_adicionales
    }
    return render(request, 'anuncios/detalle.html', contexto)


# 3. VISTA PARA PUBLICAR UN NUEVO ANUNCIO (Captura datos completos y redirige a Pago)
@login_required
def crear_anuncio(request):
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        descripcion = request.POST.get('descripcion')
        precio = request.POST.get('precio')
        categoria_id = request.POST.get('categoria')
        imagen = request.FILES.get('imagen')
        
        # 🆕 Captura de contactos de WhatsApp y Telegram
        whatsapp = request.POST.get('whatsapp', '').strip()
        telegram = request.POST.get('telegram', '').strip()

        categoria = get_object_or_404(Categoria, id=categoria_id)

        # Creación del anuncio base
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

        # 🆕 Procesamiento de imágenes adicionales múltiples
        fotos_adicionales = request.FILES.getlist('imagenes_adicionales')
        for foto in fotos_adicionales:
            ImagenAnuncio.objects.create(anuncio=nuevo_anuncio, imagen=foto)
        
        return redirect('pasarela_pago', anuncio_id=nuevo_anuncio.id)

    categorias = Categoria.objects.all()
    return render(request, 'anuncios/crear_anuncio.html', {'categorias': categorias})


# 4. PASARELA DE PAGO CON WOMPI (Preparación del cobro)
@login_required
def pasarela_pago(request, anuncio_id):
    anuncio = get_object_or_404(Anuncio, id=anuncio_id, usuario=request.user)
    
    # Valor en COP por la publicación ($5.000 COP)
    monto_cop = 5000 
    
    # Wompi requiere el valor convertido a centavos (multiplicado por 100)
    monto_centavos = int(monto_cop * 100)
    
    # Generamos una referencia única para la transacción
    referencia_pago = f"ANUNCIO-{anuncio.id}-{anuncio.usuario.id}"
    
    # Llave pública tomada de settings.py (o valor por defecto de pruebas de Wompi)
    wompi_public_key = getattr(settings, 'WOMPI_PUBLIC_KEY', 'pub_test_XXXXX')

    contexto = {
        'anuncio': anuncio,
        'monto_cop': monto_cop,
        'monto_centavos': monto_centavos,
        'referencia_pago': referencia_pago,
        'wompi_public_key': wompi_public_key,
    }
    return render(request, 'anuncios/pasarela_pago.html', contexto)


# 5. RESPUESTA Y CONFIRMACIÓN DE PAGO WOMPI
def respuesta_pago(request):
    id_transaccion = request.GET.get('id')
    
    if id_transaccion:
        # Consultamos el estado de la transacción directamente a Wompi Sandbox
        url_wompi = f"https://sandbox.wompi.co/v1/transactions/{id_transaccion}"
        try:
            response = requests.get(url_wompi, timeout=10)
            if response.status_code == 200:
                data = response.json().get('data', {})
                estado = data.get('status')       # Ej: APPROVED, DECLINED, VOIDED
                referencia = data.get('reference') # Ej: ANUNCIO-15-2
                
                if estado == 'APPROVED':
                    try:
                        # Extraemos el ID del anuncio desde la referencia (ANUNCIO-{id}-{usuario})
                        anuncio_id = referencia.split('-')[1]
                        anuncio = Anuncio.objects.get(id=anuncio_id)
                        
                        # Marcamos como pagado y registramos la fecha actual
                        anuncio.pagado = True
                        anuncio.fecha_pago = timezone.now()
                        anuncio.save()
                        
                        messages.success(request, "¡Pago aprobado con éxito! Tu anuncio ha sido publicado.")
                        return redirect('detalle_anuncio', id=anuncio.id)
                    except (IndexError, Anuncio.DoesNotExist):
                        messages.error(request, "No se encontró el anuncio correspondiente al pago.")
                else:
                    messages.warning(request, f"El pago no fue aprobado. Estado: {estado}")
        except requests.RequestException:
            messages.error(request, "Ocurrió un error al verificar la transacción con Wompi.")
            
    return redirect('mis_anuncios')


# 6. VISTA DE REGISTRO DE USUARIOS
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


# 7. VISTA: PANEL 'MIS ANUNCIOS' DEL USUARIO
@login_required
def mis_anuncios(request):
    anuncios_usuario = Anuncio.objects.filter(usuario=request.user).order_by('-id')

    contexto = {
        'anuncios': anuncios_usuario
    }
    return render(request, 'anuncios/mis_anuncios.html', contexto)


# 8. VISTA PARA EDITAR ANUNCIO PAGADO
@login_required
def editar_anuncio(request, id):
    # Obtenemos el anuncio verificando que pertenezca al usuario Y esté pagado
    anuncio = get_object_or_404(Anuncio, id=id, usuario=request.user, pagado=True)

    if request.method == 'POST':
        # Actualizar datos de texto y contactos
        anuncio.titulo = request.POST.get('titulo')
        anuncio.descripcion = request.POST.get('descripcion')
        anuncio.precio = request.POST.get('precio')
        anuncio.whatsapp = request.POST.get('whatsapp', '').strip()
        anuncio.telegram = request.POST.get('telegram', '').strip()
        
        # Actualizar categoría si se cambió
        categoria_id = request.POST.get('categoria')
        if categoria_id:
            anuncio.categoria = get_object_or_404(Categoria, id=categoria_id)

        # Actualizar foto principal (si el usuario subió una nueva)
        if request.FILES.get('imagen'):
            anuncio.imagen = request.FILES.get('imagen')

        anuncio.save()

        # Procesar fotos adicionales (si subió más imágenes)
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


# 9. VISTA PARA ELIMINAR UNA FOTO ADICIONAL
@login_required
def eliminar_foto(request, foto_id):
    foto = get_object_or_404(ImagenAnuncio, id=foto_id, anuncio__usuario=request.user)
    anuncio_id = foto.anuncio.id
    foto.delete()
    return redirect('editar_anuncio', id=anuncio_id)