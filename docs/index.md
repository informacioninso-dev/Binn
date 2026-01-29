# ERP-B22 · ERP Para pymes para uso acorde a la regulación BPADT e ISO 13485

ERP-B22 es un **micro ERP modular** pensado para pequeñas y medianas empresas que necesitan:

- Gestionar inventario con **trazabilidad por lote**.
- Controlar **recepción de materia prima**, QA y liberación.
- Manejar **finanzas básicas** (compras, ventas).
- Integrar **facturación** y, más adelante, planificación de producción.
- Alinear sus procesos a los requisitos de **ISO 13485** y regulaciones locales.

---

## Objetivos del proyecto

- Proveer una base **sólida y extensible** para crecer hacia un ERP completo.
- Mantener una arquitectura **limpia y modular**:
  - `core/` para componentes comunes (AuditModel, bodegas, ubicaciones).
  - apps separadas para `inventory`, `finance`, `billing`, `production`.
- Garantizar que los flujos críticos (recepción de MP, QA, movimientos de inventario, despacho) mantengan **trazabilidad total**.

---

## Tecnologías principales

- **Backend**: Django (Python)
- **Gestor de dependencias**: Poetry
- **Base de datos**: SQLite para desarrollo, PostgreSQL recomendado para producción
- **Frontend**: Templates Django con **Tailwind CSS utility classes**
- **Documentación**: MkDocs + Material Theme

---

## Estructura general del proyecto

```text
.
├── pyproject.toml        # Configuración de Poetry
├── mkdocs.yml            # Configuración de la documentación
├── README.md
├── docs/                 # Archivos de documentación
├── config/               # Configuración del proyecto Django (urls, settings, wsgi, asgi)
├── core/                 # Modelos y utilidades comunes
├── inventory/            # Módulo de inventario, lotes, recepciones, QA
├── finance/              # Módulo de finanzas (MVP)
├── billing/              # Módulo de facturación (MVP)
├── production/           # Módulo de producción (en evolución)
├── templates/            # Plantillas HTML (layouts, páginas)
└── static/               # Recursos estáticos (CSS, JS, imágenes)
