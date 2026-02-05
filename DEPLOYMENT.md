# Guia de Deployment - DigitalOcean

Esta guia te llevara paso a paso para hacer deployment del ERP Kore en DigitalOcean usando un Droplet con PostgreSQL local.

## Prerequisitos

- Cuenta en DigitalOcean
- Dominio configurado (kore.binnso.com)
- Acceso SSH configurado

## Fase 1: Crear el Droplet

1. Ve a [DigitalOcean Console](https://cloud.digitalocean.com/)
2. Clic en **"Create"** > **"Droplets"**
3. Configuracion recomendada:
   - **Image:** Ubuntu 24.04 LTS
   - **Plan:** Basic ($6/mes o superior)
   - **CPU:** Shared CPU
   - **RAM:** 2GB recomendado (1GB minimo)
   - **Storage:** 25GB
   - **Region:** NYC1 o el mas cercano a tus usuarios
   - **Authentication:** SSH Key (recomendado)
   - **Hostname:** kore-erp-production
4. Clic en **"Create Droplet"**
5. Anota la **IP publica** del Droplet

## Fase 2: Configurar DNS

En tu proveedor de DNS (donde administras binnso.com):

1. Agrega un registro **A**:
   - **Host:** `kore`
   - **Value:** `IP_DEL_DROPLET`
   - **TTL:** 300 (o automatico)

Esto hara que `kore.binnso.com` apunte a tu Droplet.

## Fase 3: Configurar el Servidor

### 3.1 Conectar al Droplet

```bash
ssh root@IP_DEL_DROPLET
```

### 3.2 Actualizar el sistema

```bash
apt update && apt upgrade -y
```

### 3.3 Instalar dependencias del sistema

```bash
# Python y herramientas basicas
apt install -y python3.13 python3.13-venv python3-pip git nginx curl

# Dependencias para psycopg2 y compilacion
apt install -y libpq-dev python3-dev build-essential

# Dependencias para WeasyPrint (generacion de PDFs)
apt install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev libcairo2
```

### 3.4 Instalar y configurar PostgreSQL

```bash
# Instalar PostgreSQL
apt install -y postgresql postgresql-contrib

# Iniciar y habilitar el servicio
systemctl start postgresql
systemctl enable postgresql

# Crear usuario y base de datos
sudo -u postgres psql <<EOF
CREATE USER kore_user WITH PASSWORD 'TU_PASSWORD_SEGURO';
CREATE DATABASE kore_erp OWNER kore_user;
ALTER USER kore_user CREATEDB;
GRANT ALL PRIVILEGES ON DATABASE kore_erp TO kore_user;
EOF
```

> **IMPORTANTE:** Cambia `TU_PASSWORD_SEGURO` por una contrasena segura. Anota esta contrasena, la necesitaras para el archivo `.env`.

### 3.5 Instalar Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
echo 'export PATH="/root/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
poetry --version  # Verificar instalacion
```

### 3.6 Crear usuario y directorio para la aplicacion

```bash
# Crear usuario del sistema
useradd -m -s /bin/bash kore

# Instalar Poetry para el usuario kore
sudo -u kore bash -c 'curl -sSL https://install.python-poetry.org | python3 -'
sudo -u kore bash -c 'echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> ~/.bashrc'

# Crear directorio de la aplicacion
mkdir -p /var/www/kore_erp
chown -R kore:kore /var/www/kore_erp

# Crear directorios para logs y PID
mkdir -p /var/log/gunicorn
mkdir -p /var/run/gunicorn
chown -R kore:kore /var/log/gunicorn
chown -R kore:kore /var/run/gunicorn
```

## Fase 4: Clonar y Configurar la Aplicacion

### 4.1 Clonar el repositorio

```bash
cd /var/www/kore_erp
sudo -u kore git clone https://github.com/TU_USUARIO/Kore.git .
```

### 4.2 Configurar Poetry y instalar dependencias

```bash
cd /var/www/kore_erp
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && poetry config virtualenvs.in-project true && poetry install --no-dev'
```

### 4.3 Crear archivo .env de produccion

```bash
sudo -u kore cp .env.production.example .env
sudo -u kore nano .env
```

Contenido del archivo `.env` (editar con tus valores reales):

```bash
# ---- Seguridad ----
SECRET_KEY=PEGAR_CLAVE_GENERADA_AQUI
DEBUG=False
ALLOWED_HOSTS=kore.binnso.com,IP_DEL_DROPLET
CSRF_TRUSTED_ORIGINS=https://kore.binnso.com

# ---- SSL (activar despues de configurar Certbot) ----
ENABLE_SSL=False

# ---- Base de datos ----
DB_ENGINE=postgresql
DB_NAME=kore_erp
DB_USER=kore_user
DB_PASSWORD=TU_PASSWORD_SEGURO
DB_HOST=localhost
DB_PORT=5432
```

**Para generar SECRET_KEY segura:**

```bash
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && cd /var/www/kore_erp && poetry run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"'
```

### 4.4 Aplicar migraciones y configurar

```bash
cd /var/www/kore_erp
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && poetry run python manage.py migrate'
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && poetry run python manage.py collectstatic --noinput'
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && poetry run python manage.py createsuperuser'
```

### 4.5 (Opcional) Cargar datos iniciales

```bash
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && poetry run python manage.py bootstrap_roles'
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && poetry run python manage.py seed_data'
```

## Fase 5: Configurar Gunicorn como Servicio

### 5.1 Copiar archivo de servicio

```bash
cp /var/www/kore_erp/deploy/gunicorn.service /etc/systemd/system/
```

### 5.2 Habilitar e iniciar el servicio

```bash
systemctl daemon-reload
systemctl enable gunicorn
systemctl start gunicorn
systemctl status gunicorn
```

Si el status muestra `active (running)`, Gunicorn esta funcionando.

## Fase 6: Configurar Nginx

### 6.1 Copiar configuracion de Nginx

```bash
cp /var/www/kore_erp/deploy/nginx.conf /etc/nginx/sites-available/kore_erp
```

### 6.2 Habilitar el sitio

```bash
ln -s /etc/nginx/sites-available/kore_erp /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t  # Verificar configuracion
systemctl restart nginx
```

### 6.3 Verificar acceso

Abre en tu navegador: `http://kore.binnso.com`

Si ves la pagina de login, todo esta funcionando.

## Fase 7: Configurar SSL con Let's Encrypt

```bash
# Instalar Certbot
apt install -y certbot python3-certbot-nginx

# Obtener certificado SSL
certbot --nginx -d kore.binnso.com

# Renovacion automatica
systemctl enable certbot.timer
```

### 7.1 Activar SSL en la aplicacion

Despues de que Certbot confirme el certificado, edita el `.env`:

```bash
sudo -u kore nano /var/www/kore_erp/.env
```

Cambiar `ENABLE_SSL=False` a `ENABLE_SSL=True`, luego:

```bash
systemctl restart gunicorn
```

## Deployment Completado

Tu aplicacion esta accesible en:
- **HTTPS:** https://kore.binnso.com

## Deployments Futuros

Para actualizar la aplicacion con nuevos cambios:

```bash
cd /var/www/kore_erp
sudo -u kore bash deploy/deploy.sh
```

## Comandos Utiles

```bash
# Ver logs de Gunicorn
tail -f /var/log/gunicorn/error.log

# Ver logs de Nginx
tail -f /var/log/nginx/kore_erp_error.log

# Ver logs de PostgreSQL
tail -f /var/log/postgresql/postgresql-*-main.log

# Reiniciar servicios
systemctl restart gunicorn
systemctl restart nginx
systemctl restart postgresql

# Ver estado de servicios
systemctl status gunicorn
systemctl status nginx
systemctl status postgresql

# Acceder a la consola de Django
cd /var/www/kore_erp
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && poetry run python manage.py shell'

# Crear nuevo superusuario
sudo -u kore bash -c 'export PATH="$HOME/.local/bin:$PATH" && poetry run python manage.py createsuperuser'
```

## Troubleshooting

### Error de conexion a base de datos
- Verificar credenciales en `.env`
- Verificar que PostgreSQL esta corriendo: `systemctl status postgresql`
- Probar conexion: `sudo -u postgres psql -U kore_user -d kore_erp -h localhost`

### Error 502 Bad Gateway
- Verificar que Gunicorn esta corriendo: `systemctl status gunicorn`
- Ver logs: `tail -f /var/log/gunicorn/error.log`
- Verificar socket/puerto: `ss -tlnp | grep 8000`

### Archivos estaticos no cargan
- Ejecutar: `poetry run python manage.py collectstatic --noinput`
- Verificar permisos: `chown -R kore:kore /var/www/kore_erp/staticfiles`

### Certbot falla
- Verificar que el DNS apunta al Droplet: `dig kore.binnso.com`
- Verificar que el puerto 80 esta abierto en el firewall
- Verificar que Nginx esta corriendo: `systemctl status nginx`
