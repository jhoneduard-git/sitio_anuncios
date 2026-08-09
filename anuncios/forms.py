from django import forms
from .models import Anuncio

class FormularioAnuncio(forms.ModelForm):
    class Meta:
        model = Anuncio
        # 1. Incluimos 'whatsapp' y 'telegram' junto a los demás campos
        fields = ['categoria', 'titulo', 'descripcion', 'precio', 'imagen', 'whatsapp', 'telegram']
        
        # 2. Agregamos estilos visuales y placeholders a todos los campos
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-control'}),
            'titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Vendo iPhone 14 Pro Max'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Describe detalladamente tu producto...'}),
            'precio': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 500'}),
            'imagen': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
            
            # 🆕 Widgets para datos de contacto
            'whatsapp': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Ej: 573001234567 (con código de país sin el +)'
            }),
            'telegram': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Ej: TuUsuarioTelegram (sin el @)'
            }),
        }

        # 3. Personalizamos los nombres visibles de los campos
        labels = {
            'categoria': 'Categoría',
            'titulo': 'Título del Anuncio',
            'descripcion': 'Descripción',
            'precio': 'Precio ($)',
            'imagen': 'Imagen Principal',
            'whatsapp': 'Número de WhatsApp',
            'telegram': 'Usuario de Telegram',
        }

        # 4. Mensajes de ayuda para el usuario
        help_texts = {
            'whatsapp': 'Ingresa tu número con código de país (ejemplo: 573000000000).',
            'telegram': 'Ingresa únicamente tu nombre de usuario de Telegram sin el signo @.',
        }