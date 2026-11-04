"""Configuración por entorno compartida por todos los servicios.

Cada servicio se ubica por su URL. Por defecto apuntan a 127.0.0.1 (ejecución local en Windows/XAMPP);
en Docker Compose se sobreescriben con variables de entorno (p. ej. MENU_URL=http://menu:8003).
"""
import os

PUERTOS = {
    "usuarios": 8001,
    "restaurantes": 8002,
    "menu": 8003,
    "pedidos": 8004,
    "pagos": 8005,
    "domicilios": 8006,
    "notificaciones": 8007,
}


def url(servicio):
    """URL base de un microservicio (sin barra final)."""
    return os.getenv(f"{servicio.upper()}_URL", f"http://127.0.0.1:{PUERTOS[servicio]}").rstrip("/")


# Broker de mensajería. Vacío = sin RabbitMQ: los eventos viajan por HTTP directo (modo de respaldo).
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "").strip()
