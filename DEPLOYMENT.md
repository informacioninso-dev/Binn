# 🚀 Guía de Deployment - DigitalOcean

Esta guía te llevará paso a paso para hacer deployment del ERP en DigitalOcean usando un Droplet + PostgreSQL administrado.

## 📋 Prerequisitos

- Cuenta en DigitalOcean
- Dominio configurado (opcional pero recomendado)
- Acceso SSH configurado

## 🏗️ Fase 1: Crear Recursos en DigitalOcean

### 1.1 Crear Droplet

1. Ve a [DigitalOcean Console](https://cloud.digitalocean.com/)
2. Clic en **"Create"** → **"Droplets"**
3. Configuración recomendada:
   - **Image:** Ubuntu 24.04 LTS
   - **Plan:** Basic ($6/mes o superior según necesidad)
   - **CPU:** Shared CPU
   - **RAM:** 1GB mínimo (2GB recomendado)
   - **Storage:** 25GB
   - **Region:** Elegir el más cercano a tus usuarios
   - **Authentication:** SSH Key (recomendado)
   - **Hostname:** kore-erp-production

4. Clic en **"Create Droplet"**
5. Anota la **IP pública** del Droplet

### 1.2 Crear Base de Datos PostgreSQL

1. En DigitalOcean, clic en **"Create"** → **"Databases"**
2. Configuración:
   - **Engine:** PostgreSQL 16
   - **Plan:** Basic ($15/mes)
   - **Node:** 1 node
   - **RAM:** 1GB
   - **Region:** Mismo que el Droplet
   - **Database name:** kore-erp-db

3. Clic en **"Create Database Cluster"**
4. Una vez creado, ve a la pestaña **"Users & Databases"**
5. Crea una base de datos llamada `kore_erp`
6. Anota las credenciales:
   - Host
   - Port
   - User
   - Password
   - Database

7. En **"Settings"** → **"Trusted Sources"**, agrega la IP de tu Droplet

## 🔧 Fase 2: Configurar el Servidor

### 2.1 Conectar al Droplet

```bash
ssh root@YOUR_DROPLET_IP
```

### 2.2 Actualizar el sistema

```bash
apt update && apt upgrade -y
```

### 2.3 Instalar dependencias del sistema

```bash
# Python y herramientas básicas
apt install -y python3.13 python3.13-venv python3-pip git nginx curl

# Dependencias para psycopg2 y Pillow
apt install -y postgresql-client libpq-dev python3-dev build-essential

# Dependencias para WeasyPrint y xhtml2pdf
apt install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev libcairo2
```

### 2.4 Instalar Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
echo 'export PATH="/root/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 2.5 Crear usuario y directorio para la aplicación

```bash
# Crear usuario
useradd -m -s /bin/bash kore

# Crear directorio de la aplicación
mkdir -p /var/www/kore_erp
chown -R kore:kore /var/www/kore_erp

# Crear directorios para logs
mkdir -p /var/log/gunicorn
mkdir -p /var/run/gunicorn
chown -R kore:kore /var/log/gunicorn
chown -R kore:kore /var/run/gunicorn
```

## 📦 Fase 3: Clonar y Configurar la Aplicación

### 3.1 Clonar el repositorio

```bash
cd /var/www/kore_erp
sudo -u kore git clone https://github.com/informacioninso-dev/Kore.git .
```

### 3.2 Configurar Poetry y instalar dependencias

```bash
cd /var/www/kore_erp
sudo -u kore poetry config virtualenvs.in-project true
sudo -u kore poetry install --no-dev
```

### 3.3 Crear archivo .env de producción

```bash
sudo -u kore nano /var/www/kore_erp/.env
```

Contenido del archivo `.env`:

```bash
# ---- Seguridad ----
SECRET_KEY=GENERAR_CLAVE_SECRETA_AQUI
DEBUG=False
ALLOWED_HOSTS=tu-dominio.com,www.tu-dominio.com,IP_DEL_DROPLET
CSRF_TRUSTED_ORIGINS=https://tu-dominio.com,https://www.tu-dominio.com

# ---- Base de datos ----
DB_ENGINE=postgresql
DB_NAME=kore_erp
DB_USER=doadmin
DB_PASSWORD=PASSWORD_DE_DIGITALOCEAN
DB_HOST=HOST_DE_DIGITALOCEAN
DB_PORT=25060
```

**Para generar SECRET_KEY segura:**
```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 3.4 Aplicar migraciones y configurar archivos estáticos

```bash
cd /var/www/kore_erp
sudo -u kore poetry run python manage.py migrate
sudo -u kore poetry run python manage.py collectstatic --noinput
sudo -u kore poetry run python manage.py createsuperuser
```

## 🔄 Fase 4: Configurar Gunicorn como Servicio

### 4.1 Copiar archivo de servicio

```bash
cp /var/www/kore_erp/deploy/gunicorn.service /etc/systemd/system/
```

### 4.2 Ajustar permisos y rutas

```bash
# Editar el servicio si es necesario
nano /etc/systemd/system/gunicorn.service

# Cambiar User y Group a 'kore' si usas ese usuario
```

### 4.3 Habilitar e iniciar el servicio

```bash
systemctl daemon-reload
systemctl enable gunicorn
systemctl start gunicorn
systemctl status gunicorn
```

## 🌐 Fase 5: Configurar Nginx

### 5.1 Copiar configuración de Nginx

```bash
cp /var/www/kore_erp/deploy/nginx.conf /etc/nginx/sites-available/kore_erp
```

### 5.2 Editar configuración

```bash
nano /etc/nginx/sites-available/kore_erp
```

Actualizar:
- `server_name` con tu dominio
- Rutas si es necesario

### 5.3 Habilitar el sitio

```bash
ln -s /etc/nginx/sites-available/kore_erp /etc/nginx/sites-enabled/
rm /etc/nginx/sites-enabled/default  # Opcional
nginx -t  # Verificar configuración
systemctl restart nginx
```

## 🔒 Fase 6: Configurar SSL con Let's Encrypt

```bash
# Instalar Certbot
apt install -y certbot python3-certbot-nginx

# Obtener certificado SSL
certbot --nginx -d tu-dominio.com -d www.tu-dominio.com

# Renovación automática
systemctl enable certbot.timer
```

## 🎉 ¡Deployment Completado!

Tu aplicación debería estar accesible en:
- **HTTP:** http://tu-dominio.com
- **HTTPS:** https://tu-dominio.com

## 🔄 Deployments Futuros

Para actualizar la aplicación:

```bash
cd /var/www/kore_erp
sudo -u kore bash deploy/deploy.sh
```

## 📊 Comandos Útiles

```bash
# Ver logs de Gunicorn
tail -f /var/log/gunicorn/error.log

# Ver logs de Nginx
tail -f /var/log/nginx/kore_erp_error.log

# Reiniciar servicios
systemctl restart gunicorn
systemctl restart nginx

# Ver estado de servicios
systemctl status gunicorn
systemctl status nginx
```

## 🆘 Troubleshooting

### Error de conexión a base de datos
- Verificar credenciales en `.env`
- Verificar que la IP del Droplet esté en "Trusted Sources" de PostgreSQL

### Error 502 Bad Gateway
- Verificar que Gunicorn esté corriendo: `systemctl status gunicorn`
- Ver logs: `tail -f /var/log/gunicorn/error.log`

### Archivos estáticos no cargan
- Ejecutar: `poetry run python manage.py collectstatic --noinput`
- Verificar permisos: `chown -R kore:kore /var/www/kore_erp/staticfiles`
