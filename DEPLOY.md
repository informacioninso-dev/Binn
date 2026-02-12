# Guía de Deployment a Producción

## Pre-requisitos

- Servidor Linux (Ubuntu 22.04 recomendado)
- PostgreSQL 14+
- Dominio `binnso.com` configurado con DNS
- Acceso SSH al servidor

## 1. Configurar DNS

En tu panel de DNS (Cloudflare, GoDaddy, etc.), agrega:

```
Tipo    Nombre    Valor (IP del servidor)
A       *         123.45.67.89
A       @         123.45.67.89
```

El wildcard `*` hace que cualquier subdominio (`demo.binnso.com`, `acme.binnso.com`) apunte a tu servidor.

## 2. Variables de entorno (.env en producción)

```env
SECRET_KEY=genera-un-secreto-seguro-de-50-caracteres
DEBUG=False
ALLOWED_HOSTS=.binnso.com,binnso.com

DB_ENGINE=postgresql
DB_NAME=kore_production
DB_USER=kore_user
DB_PASSWORD=password-seguro-aqui
DB_HOST=localhost
DB_PORT=5432

TENANT_BASE_DOMAIN=binnso.com
```

## 3. SSL con Caddy (opción recomendada)

### Instalar Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

### Configurar Caddyfile

```
# /etc/caddy/Caddyfile

*.binnso.com, binnso.com {
    reverse_proxy localhost:8000
    encode gzip
}

# Si kore.binnso.com es página comercial separada
kore.binnso.com {
    root * /var/www/kore-marketing
    file_server
}
```

### Iniciar Caddy

```bash
sudo systemctl enable caddy
sudo systemctl start caddy
```

Caddy automáticamente:
- Obtiene certificado wildcard SSL de Let's Encrypt
- Renueva antes de expirar
- Sirve en HTTPS

## 4. Configurar PostgreSQL

```bash
sudo -u postgres psql

CREATE DATABASE kore_production;
CREATE USER kore_user WITH PASSWORD 'password-seguro-aqui';
ALTER ROLE kore_user SET client_encoding TO 'utf8';
ALTER ROLE kore_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE kore_user SET timezone TO 'America/Guayaquil';
GRANT ALL PRIVILEGES ON DATABASE kore_production TO kore_user;
\q
```

## 5. Deployment con Gunicorn

### Instalar dependencias

```bash
cd /opt/kore
poetry install --no-dev
```

### Migrar schemas

```bash
poetry run python manage.py migrate_schemas --shared
```

### Crear tenant público

```bash
poetry run python manage.py shell

from tenants.models import Client, Domain
from django.db import connection

c = connection.cursor()
c.execute("INSERT INTO tenants_client (schema_name, name, plan, is_active, created_on) VALUES ('public', 'Kore Platform', 'shared', true, CURRENT_DATE)")
connection.commit()

c.execute("SELECT id FROM tenants_client WHERE schema_name='public'")
client_id = c.fetchone()[0]

c.execute("INSERT INTO tenants_domain (domain, tenant_id, is_primary) VALUES ('app.binnso.com', %s, true)", [client_id])
connection.commit()
```

### Crear superusuario

```bash
poetry run python manage.py createsuperuser
```

### Configurar systemd service

```ini
# /etc/systemd/system/kore.service

[Unit]
Description=Kore ERP
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/kore
Environment="PATH=/opt/kore/.venv/bin"
ExecStart=/opt/kore/.venv/bin/gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 4 \
    --worker-class sync \
    --timeout 120 \
    --access-logfile /var/log/kore/access.log \
    --error-logfile /var/log/kore/error.log

[Install]
WantedBy=multi-user.target
```

### Iniciar servicio

```bash
sudo mkdir -p /var/log/kore
sudo chown www-data:www-data /var/log/kore
sudo systemctl enable kore
sudo systemctl start kore
```

## 6. Crear primer tenant

1. Accede a `https://app.binnso.com/login`
2. Inicia sesión con el superusuario
3. Ve a `https://app.binnso.com/tenants/nuevo/`
4. Crea un tenant:
   - Nombre: "Demo"
   - Schema: "demo"
   - Subdominio: "demo" (se convertirá en `demo.binnso.com`)
   - Plan: Shared
   - Admin: crear usuario admin para ese tenant

5. Click "Entrar" te llevará a `https://demo.binnso.com/`

## 7. Monitoreo

### Logs de Caddy
```bash
sudo journalctl -u caddy -f
```

### Logs de Kore
```bash
tail -f /var/log/kore/error.log
```

### Verificar certificados SSL
```bash
curl -vI https://demo.binnso.com 2>&1 | grep -i "SSL"
```

## 8. Backups

### Backup de base de datos (todos los schemas)
```bash
pg_dump -U kore_user -h localhost kore_production > backup_$(date +%Y%m%d).sql
```

### Backup de un schema específico
```bash
pg_dump -U kore_user -h localhost -n demo kore_production > backup_demo_$(date +%Y%m%d).sql
```

### Restaurar
```bash
psql -U kore_user -h localhost kore_production < backup_20260210.sql
```

## Troubleshooting

### Error: "No tenant for hostname"
- Verifica que el dominio esté registrado en `tenants_domain`
- Verifica DNS con `nslookup demo.binnso.com`

### Error 502 Bad Gateway
- Verifica que Gunicorn esté corriendo: `sudo systemctl status kore`
- Verifica logs: `tail /var/log/kore/error.log`

### SSL no funciona
- Verifica que el puerto 443 esté abierto: `sudo ufw allow 443`
- Verifica logs de Caddy: `sudo journalctl -u caddy -f`
- Verifica que DNS apunte al servidor correcto

## Seguridad adicional

### Firewall
```bash
sudo ufw allow 22   # SSH
sudo ufw allow 80   # HTTP (Caddy redirige a HTTPS)
sudo ufw allow 443  # HTTPS
sudo ufw enable
```

### Fail2ban (protección contra brute force)
```bash
sudo apt install fail2ban
```

### Actualizaciones automáticas de seguridad
```bash
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```
