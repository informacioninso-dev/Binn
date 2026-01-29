Hilo 1 – Materia prima → producto final

Recepción de MP (con lote proveedor).


Almacenamiento por lote de materia prima ( recepción)

Consumo por bodega ( Unidades: modelo de configutacion de unidades)
modulo de configuracion de bodegas. consdierar bodega de acondcionmaineto como obligatorio.


Generación de lotes de producto terminado con:

- lote MP
- lote genral

- fecha fabricación
- expira cuando aplica
- RS
- fecha de vencimiento (si aplica)
- condicion de almacenamieto
puntos de control con calidad , bloqquenado

Hilo 2 – Pedido → Despacho → Factura → Guía de remisión

Pedido del cliente (Order). 

Asignación de lotes a ese pedido. FEFO.

Despacho (Picking/Remisión interna).

Factura.

Guía de remisión física para transporte.

# ERP-B22 – Micro ERP para ISO 13485

## Descripción

Sistema ERP modular para PYMEs con enfoque en:
- Inventario con trazabilidad por lote (ISO 13485).
- Finanzas básicas.
- Facturación.
- Planificación de producción.

## Tecnologías

- Python 3.12+ (gestionado con Poetry)
- Django 4.x
- Tailwind CSS (clases utilitarias en templates)
- PostgreSQL (opcional, según tu setup)

## Instalación (Poetry)

```bash
git clone <url-del-repo>
cd erp-b22
poetry install
poetry shell

# aplicar migraciones
poetry run python manage.py makemigrations  
poetry run python manage.py  showmigrations    |
poetry run python manage.py migrate

# crear superusuario
poetry run python manage.py createsuperuser

# levantar servidor
poetry run python manage.py runserver


## Arreglo del problema de que no se encuntra la versión de python correpondiente

poetry env info # Revisión de como esta configurado en entorno virtual
poetry env list
python --version
poetry env remove erp-py3.13
poetry env remove --all
poetry env use " "

poetry install --sync.

## Revisar el tree del codigo
tree /f > tree.txt

 Get-ChildItem -Recurse -Filter *.py | Select-String "class BillOfMaterial"




##################################
## Activación del sistema            ##
##################################


poetry run python manage.py makemigrations 
poetry run python manage.py migrate

poetry run python manage.py makemigrations core 
poetry run python manage.py migrate core

poetry run python manage.py makemigrations inventory
poetry run python manage.py migrate inventory

poetry run python manage.py makemigrations  partners
poetry run python manage.py migrate partners

poetry run python manage.py makemigrations procurement
poetry run python manage.py migrate procurement

poetry run python manage.py makemigrations production
poetry run python manage.py migrate production

poetry run python manage.py makemigrations quality
poetry run python manage.py migrate quality

poetry run python manage.py makemigrations sales
poetry run python manage.py migrate sales

## Generacion de SEED
poetry run python manage.py seed_data 
poetry run python manage.py bootstrap_roles.py

## Crear superadmin
poetry run python manage.py createsuperuser
poetry run python manage.py shell

## Arancar el servidor
poetry run python manage.py runserver
