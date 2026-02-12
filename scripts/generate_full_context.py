# generate_full_context.py
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.apps import apps
from django.urls import get_resolver
from django.conf import settings

with open('project_context.txt', 'w', encoding='utf-8') as f:
    # 1. INFORMACIÓN GENERAL
    f.write("="*60 + "\n")
    f.write("CONTEXTO DEL PROYECTO DJANGO\n")
    f.write("="*60 + "\n\n")
    
    f.write(f"Proyecto: {settings.ROOT_URLCONF.split('.')[0]}\n")
    f.write(f"Base de datos: {settings.DATABASES['default']['ENGINE']}\n")
    f.write(f"Apps instaladas: {len([a for a in settings.INSTALLED_APPS if not a.startswith('django.')])}\n\n")
    
    # 2. MODELOS DETALLADOS
    f.write("\n" + "="*60 + "\n")
    f.write("MODELOS Y CAMPOS\n")
    f.write("="*60 + "\n")
    
    for app_config in apps.get_app_configs():
        if app_config.name.startswith('django.'):
            continue
            
        models = app_config.get_models()
        if not models:
            continue
            
        f.write(f"\n{'─'*60}\n")
        f.write(f"APP: {app_config.label}\n")
        f.write(f"{'─'*60}\n")
        
        for model in models:
            f.write(f"\n  Modelo: {model.__name__}\n")
            f.write(f"  Tabla: {model._meta.db_table}\n")
            
            # Campos
            f.write(f"\n  Campos:\n")
            for field in model._meta.get_fields():
                field_type = field.__class__.__name__
                field_info = f"    • {field.name} ({field_type})"
                
                # Agregar detalles extra
                if hasattr(field, 'max_length') and field.max_length:
                    field_info += f" [max_length={field.max_length}]"
                if hasattr(field, 'null') and field.null:
                    field_info += " [null=True]"
                if hasattr(field, 'blank') and field.blank:
                    field_info += " [blank=True]"
                if hasattr(field, 'related_model') and field.related_model:
                    field_info += f" -> {field.related_model.__name__}"
                    
                f.write(field_info + "\n")
            
            # Métodos personalizados
            custom_methods = [m for m in dir(model) if not m.startswith('_') and callable(getattr(model, m))]
            django_methods = ['check', 'clean', 'delete', 'save', 'get_absolute_url', 'prepare_database_save', 'refresh_from_db', 'save_base', 'serializable_value', 'validate_unique', 'full_clean']
            custom_only = [m for m in custom_methods if m not in django_methods]
            
            if custom_only[:10]:  # Limitar a 10 para no saturar
                f.write(f"\n  Métodos custom: {', '.join(custom_only[:10])}\n")
            
            f.write("\n")
    
    # 3. URLS
    f.write("\n" + "="*60 + "\n")
    f.write("URLS PRINCIPALES\n")
    f.write("="*60 + "\n\n")
    
    try:
        urlpatterns = get_resolver().url_patterns
        for pattern in urlpatterns[:20]:  # Primeras 20 URLs
            f.write(f"  • {pattern.pattern}\n")
    except:
        f.write("  (No se pudieron extraer las URLs)\n")
    
    # 4. APPS PERSONALIZADAS
    f.write("\n" + "="*60 + "\n")
    f.write("APPS DEL PROYECTO\n")
    f.write("="*60 + "\n\n")
    
    for app in settings.INSTALLED_APPS:
        if not app.startswith('django.'):
            f.write(f"  • {app}\n")

print("✅ Contexto generado en: project_context.txt")
print("📄 Puedes copiar y pegar ese archivo completo en el chat")