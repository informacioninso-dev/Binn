Actúa como arquitecto de software ERP especializado en inventarios, costos y control contable, con experiencia en sistemas productivos y normativas de calidad (ISO 13485 / control interno).

El objetivo es definir una arquitectura sólida y coherente para la gestión de unidades de medida, conversiones, inventarios, consumos y costos, evitando errores de stock, inconsistencias contables y problemas de auditoría.
Contexto del sistema

El sistema es un ERP modular (compras, inventarios, producción, calidad).

Maneja materias primas, insumos y productos con distintas unidades de medida (kg, g, m, cm, unidades).

Se requiere trazabilidad física y contable.

El sistema debe ser auditable, estable y consistente en el tiempo.

1️⃣ Principios obligatorios del diseño
1. Unidad base única por producto

Cada producto DEBE tener una unidad base definida (base_unit).

Esa unidad base es la única usada para almacenar cantidades en base de datos.

Ejemplos:

Tela → unidad base: kg

Hilo → unidad base: kg

Tornillos → unidad base: unidad

Tubos → unidad base: metro

2. Almacenamiento interno (Base de datos)

Todas las cantidades físicas se guardan en unidad base

Todos los costos se guardan por unidad base

Precisión mínima obligatoria: 4 decimales

Ejemplo:

stock_qty = 1.0250   (kg)
unit_cost = 4.3782  (USD/kg)


📌 Nunca se guarda stock en unidades “de visualización” (g, mg, cm, etc.)

3. Unidades de medida (UoM)

Las unidades:

Vienen precargadas (seed del sistema).

Son administrables solo por roles autorizados.

Cada unidad tiene:

factor_to_base

Relación matemática clara con la unidad base.

Regla de conversión correcta

El factor_to_base siempre indica cuánto equivale ESA unidad en la unidad base

Ejemplo (base = kg):

Unidad	factor_to_base
kg	1.0000
g	0.0010
mg	0.000001

❌ Nunca usar factores invertidos (ej. kg = 1000).

2️⃣ Conversión de unidades (Regla central)
Conversión SIEMPRE mediante un service central

No se permiten conversiones:

en formularios

en vistas

en templates

“a mano”

Debe existir un service único y reutilizable, por ejemplo:

core/services/uom.py


Funciones mínimas obligatorias:

Convertir a unidad base

Convertir desde unidad base

(Opcional) Sugerir unidad de visualización

Ejemplo conceptual de conversión

Entrada usuario (UI):

Cantidad: 25
Unidad: g


Proceso interno:

25 × 0.001 = 0.025 kg


Guardado en BD:

stock_qty = 0.0250 kg

3️⃣ Flujo correcto por módulo
📦 Compras / Recepciones

El usuario ingresa cantidad y unidad “humana”.

El sistema:

Convierte a unidad base.

Guarda stock y costo en unidad base.

Nunca se guarda la cantidad “tal como se ingresó”.

🏭 Producción / Consumos

El usuario puede consumir:

25 g

0.3 kg

El sistema:

Convierte a base.

Resta stock base.

Calcula costo con unit_cost base.

Ejemplo:

Consumo: 25 g
→ 0.025 kg
Costo = 0.025 × costo_por_kg

📊 Contabilidad y costos

Todos los cálculos usan:

cantidades en unidad base

costos con 4 decimales

Esto garantiza:

consistencia

conciliación contable

auditoría sin desviaciones

4️⃣ Visualización (UI amigable)

El sistema puede mostrar unidades distintas a la base:

stock < 1 kg → mostrar en g

stock ≥ 1 kg → mostrar en kg

Esto es solo visual, nunca afecta la BD.

Ejemplo:

BD: 0.7500 kg
UI: 750 g

5️⃣ Reglas de seguridad y gobierno de datos

❌ No permitir cambiar factor_to_base de una unidad si ya existen movimientos.

❌ No permitir cambiar base_unit de un producto con stock.

✅ Todo cambio de unidades debe quedar trazado (quién, cuándo, por qué).

6️⃣ Regla contable clave

Todo valor físico y económico se maneja con mínimo 4 decimales, incluso si la UI muestra menos.

Esto evita:

errores de redondeo acumulados

diferencias en cierres mensuales

descuadres entre físico vs contable

7️⃣ Resultado esperado

Con este diseño:

El sistema maneja kg y g sin errores

Soporta consumos pequeños y grandes

Mantiene coherencia física, operativa y contable

Es auditable, escalable y robusto