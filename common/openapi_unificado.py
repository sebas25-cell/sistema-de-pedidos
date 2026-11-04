"""Une las especificaciones OpenAPI de los 7 microservicios en una sola, tal como se ven a través del gateway.

Cada ruta recibe el prefijo de su servicio (/pedidos/pedidos), los modelos se renombran con el servicio
(pedidos_CambioEstado) para evitar choques, y las etiquetas se agrupan por servicio.
Lo usan el gateway (Swagger en /docs) y `exportar_openapi.py` (archivos JSON de entrega).
"""
import json
import re

from common.app import VERSION

COMUNES = {"HTTPValidationError", "ValidationError", "Error"}   # idénticos en todos los servicios: se comparten

RESUMEN = (
    "Punto de entrada único de la solución. **Todas las llamadas del navegador pasan por el gateway** "
    "(`http://localhost:8000/<servicio>/<ruta>`), que las dirige al microservicio correspondiente.\n\n"
    "| Servicio | Responsabilidad |\n|---|---|\n"
    "| usuarios | Registro, login (JWT), roles y disponibilidad de repartidores |\n"
    "| restaurantes | Catálogo de restaurantes |\n"
    "| menu | Productos e inventario |\n"
    "| pedidos | Ciclo de vida del pedido y máquina de estados |\n"
    "| pagos | Pago de cada pedido |\n"
    "| domicilios | Asignación y avance del reparto |\n"
    "| notificaciones | Avisos al cliente y al repartidor (consume eventos de RabbitMQ) |\n\n"
    "**Autenticación:** inicia sesión en `POST /usuarios/login`, copia el `token`, pulsa **Authorize** y pégalo. "
    "Cuentas de prueba: `admin@monteria.com / admin123`, `cliente@monteria.com / cliente123`, "
    "`carlos@monteria.com / reparto123`.")


def unir(specs, servidor="http://localhost:8000", faltan=()):
    """specs: {nombre_servicio: dict openapi}. Devuelve una única especificación OpenAPI 3."""
    descripcion = RESUMEN
    if faltan:
        descripcion += "\n\n> ⚠️ Servicios no disponibles al generar este documento: " + ", ".join(faltan)
    salida = {
        "openapi": "3.1.0",
        "info": {"title": "Sistema de Pedidos para Restaurantes · API unificada", "version": VERSION,
                 "description": descripcion},
        "servers": [{"url": servidor}],
        "tags": [],
        "paths": {},
        "components": {"schemas": {}, "securitySchemes": {}},
    }
    for svc, spec in specs.items():
        texto = json.dumps(spec)
        texto = re.sub(r"#/components/schemas/([A-Za-z0-9_.\-]+)",
                       lambda m: "#/components/schemas/" + (m.group(1) if m.group(1) in COMUNES else f"{svc}_{m.group(1)}"),
                       texto)
        s = json.loads(texto)
        comp = s.get("components", {})
        for nombre, esquema in comp.get("schemas", {}).items():
            salida["components"]["schemas"][nombre if nombre in COMUNES else f"{svc}_{nombre}"] = esquema
        salida["components"]["securitySchemes"].update(comp.get("securitySchemes", {}))
        for ruta, operaciones in s.get("paths", {}).items():
            for op in operaciones.values():
                if isinstance(op, dict):
                    op["tags"] = [f"{svc} · {t}" for t in op.get("tags", [])] or [svc]
                    if "operationId" in op:
                        op["operationId"] = f"{svc}_{op['operationId']}"
            salida["paths"][f"/{svc}{ruta}"] = operaciones
        for t in s.get("tags", []):
            salida["tags"].append({"name": f"{svc} · {t['name']}", "description": t.get("description", "")})
    return salida
