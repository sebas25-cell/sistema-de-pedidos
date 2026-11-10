import logging
import time

import requests
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common import observabilidad
from common.auth import requiere

VERSION = "4.0.0"


class Error(BaseModel):
    """Formato de todas las respuestas de error del sistema."""
    detail: str


_TEXTOS_ERROR = {
    400: "Datos inválidos o regla de negocio no cumplida",
    401: "Sin sesión, token inválido o vencido",
    403: "El rol del usuario no tiene permiso para esta acción",
    404: "El recurso no existe",
    409: "Conflicto con el estado actual del recurso",
    422: "Error de validación del cuerpo o los parámetros",
    429: "Demasiados intentos, espera antes de reintentar",
    502: "Falló un servicio del que depende esta operación",
    503: "Un servicio del que depende esta operación no está disponible",
}


def errores(*codigos):
    """Respuestas de error para documentar en Swagger: responses=errores(401, 403, 404)."""
    # el 422 de validación lo documenta FastAPI solo (con su propio formato), por eso se omite aquí
    return {c: {"model": Error, "description": _TEXTOS_ERROR[c]} for c in codigos if c != 422}


def create_app(titulo, descripcion="", db=None, tags=None, lifespan=None, **kw):
    """Crea la aplicación FastAPI de un microservicio con CORS, logs, métricas, /health y /metrics.

    db: nombre de la base de datos del servicio; si se indica, /health comprueba que responda.
    """
    app = FastAPI(
        title=f"Servicio {titulo}",
        description=descripcion,
        version=VERSION,
        openapi_tags=tags or [],
        lifespan=lifespan,
        **kw,
        contact={"name": "Sistema de Pedidos para Restaurantes - Montería"},
    )
    # Solo se aceptan navegadores abiertos desde localhost / 127.0.0.1 (cualquier puerto) o desde un archivo local
    app.add_middleware(
        CORSMiddleware,
                allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|https://[a-z0-9-]+\.vercel\.app|null)$",
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    metricas = observabilidad.instalar(app, titulo)
    log = observabilidad.configurar_logging(titulo)

    @app.exception_handler(Exception)
    async def error_interno(request, exc):
        # El detalle y el traceback ya quedaron en el log (middleware); al cliente solo se le da el id para soporte.
        return JSONResponse({"detail": "Error interno del servidor", "request_id": getattr(request.state, "rid", "-")},
                            status_code=500)

    @app.get("/health", tags=["Monitoreo"], summary="Estado del servicio",
             description="Devuelve 200 si el servicio y su base de datos responden, o 503 si algo falla. "
                         "Lo usan los healthchecks de Docker y el panel de monitoreo.")
    def health():
        info = {"servicio": titulo, "ok": True, "version": VERSION, "uptime_s": int(time.time() - metricas.inicio)}
        if db:
            try:
                from common.db import query
                query(db, "SELECT 1")
                info["db"] = "ok"
            except Exception as e:
                info["db"] = "error"
                info["ok"] = False
                log.error("Health: la base de datos %s no responde: %s", db, e)
        for f in metricas._proveedores:
            try:
                extra = f()
                info.update({k: v for k, v in extra.items() if k in ("broker",)})
            except Exception:
                pass
        return JSONResponse(info, status_code=200 if info["ok"] else 503)

    @app.get("/metrics", tags=["Monitoreo"], summary="Métricas del servicio (solo ADMIN)",
             description="Peticiones, errores por clase, latencia media y p95, rutas más usadas, errores y avisos recientes.")
    def metrics(u=Depends(requiere("ADMIN"))):
        return metricas.snapshot()

    app.state.log = log
    return app


def llamar(metodo, url, **kwargs):
    """Llamada HTTP entre servicios, firmada con la clave interna y con el mismo X-Request-ID.
    Devuelve la respuesta o None si el servicio no responde."""
    from common.auth import INTERNAL_KEY
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["X-Internal-Key"] = INTERNAL_KEY
    rid = observabilidad.request_id_var.get()
    if rid != "-":
        headers["X-Request-ID"] = rid
    try:
        return requests.request(metodo, url, headers=headers, timeout=5, **kwargs)
    except requests.RequestException as e:
        logging.getLogger("app.comun").warning("Llamada %s %s falló: %s", metodo, url, type(e).__name__)
        return None


def detalle_error(r, defecto="Error en el servicio"):
    """Extrae el mensaje 'detail' de una respuesta de error de otro servicio."""
    try:
        d = r.json().get("detail")
        return d if isinstance(d, str) else defecto
    except Exception:
        return defecto
