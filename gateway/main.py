import asyncio
import time

import httpx
from fastapi import Depends, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse

from common import config
from common.app import create_app, errores
from common.auth import INTERNAL_KEY, requiere
from common.openapi_unificado import unir

SERVICIOS = list(config.PUERTOS)
client = httpx.AsyncClient(timeout=30)

app = create_app(
    "gateway",
    docs_url=None, openapi_url=None,        # el Swagger propio es el unificado (rutas /docs y /openapi.json más abajo)
    descripcion="API Gateway: único punto de entrada. Enruta `/<servicio>/<ruta>` al microservicio correspondiente.",
)
log = app.state.log
_cache_openapi = {"ts": 0.0, "spec": None}


# ------------------------------------------------------------------ documentación unificada
@app.get("/openapi.json", include_in_schema=False)
async def openapi_unificado():
    """OpenAPI de todos los servicios en un solo documento (cache de 30 s)."""
    if _cache_openapi["spec"] and time.time() - _cache_openapi["ts"] < 30:
        return JSONResponse(_cache_openapi["spec"])
    specs, faltan = {}, []

    async def pedir(nombre):
        try:
            r = await client.get(f"{config.url(nombre)}/openapi.json", timeout=3)
            specs[nombre] = r.json()
        except Exception:
            faltan.append(nombre)
            log.warning("No se pudo leer el OpenAPI de %s", nombre)

    await asyncio.gather(*(pedir(n) for n in SERVICIOS))
    ordenados = {n: specs[n] for n in SERVICIOS if n in specs}
    spec = unir(ordenados, faltan=sorted(faltan))
    if not faltan:
        _cache_openapi.update(ts=time.time(), spec=spec)
    return JSONResponse(spec)


@app.get("/docs", include_in_schema=False)
async def swagger():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Sistema de Pedidos · API unificada (Swagger)",
                               swagger_ui_parameters={"persistAuthorization": True, "docExpansion": "none",
                                                      "tagsSorter": "alpha", "filter": True})


# ------------------------------------------------------------------ monitoreo
async def _sonda(nombre):
    base, t0 = config.url(nombre), time.perf_counter()
    try:
        h = await client.get(f"{base}/health", timeout=3)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        try:
            salud = h.json()
        except Exception:
            salud = {}
        try:
            m = await client.get(f"{base}/metrics", headers={"X-Internal-Key": INTERNAL_KEY}, timeout=3)
            metricas = m.json() if m.status_code == 200 else None
        except Exception:
            metricas = None
        return {"nombre": nombre, "estado": "ok" if h.status_code == 200 else "degradado",
                "latencia_ms": ms, "salud": salud, "metricas": metricas}
    except Exception as e:
        log.error("Monitoreo: %s no responde (%s)", nombre, type(e).__name__)
        return {"nombre": nombre, "estado": "caido", "latencia_ms": None, "salud": {}, "metricas": None,
                "error": type(e).__name__}


@app.get("/estado", tags=["Monitoreo"], summary="¿Están arriba todos los servicios?",
         description="Público y mínimo: `ok` y, por servicio, si responde. Para el detalle usa `/monitor`.")
async def estado():
    sondas = await asyncio.gather(*(_sonda(n) for n in SERVICIOS))
    servicios = {s["nombre"]: s["estado"] == "ok" for s in sondas}
    return {"ok": all(servicios.values()), "servicios": servicios}


@app.get("/monitor", tags=["Monitoreo"], summary="Panel de monitoreo completo (ADMIN)",
         description="Salud, latencia y métricas de cada servicio (peticiones, errores, p95, últimos errores y avisos) "
                     "más las del propio gateway. Lo muestra la página `monitor.html`.",
         responses=errores(401, 403))
async def monitor(u=Depends(requiere("ADMIN"))):
    sondas = await asyncio.gather(*(_sonda(n) for n in SERVICIOS))
    propio = {"nombre": "gateway", "estado": "ok", "latencia_ms": 0, "salud": {"servicio": "gateway", "ok": True},
              "metricas": app.state.metricas.snapshot()}
    return {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "servicios": [propio, *sondas]}


# ------------------------------------------------------------------ proxy
@app.api_route("/{servicio}/{ruta:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"], include_in_schema=False)
async def proxy(servicio: str, ruta: str, request: Request):
    if servicio not in config.PUERTOS:
        return JSONResponse({"detail": "Servicio desconocido"}, status_code=404)
    # Solo se reenvían el tipo de contenido, el token del usuario y el id de petición;
    # la clave interna nunca viaja desde el navegador.
    headers = {"content-type": request.headers.get("content-type", "application/json"),
               "x-request-id": getattr(request.state, "rid", "")}
    if "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    try:
        r = await client.request(request.method, f"{config.url(servicio)}/{ruta}",
                                 params=request.query_params, content=await request.body(), headers=headers)
    except httpx.RequestError as e:
        log.error("Servicio %s no disponible (%s)", servicio, type(e).__name__)
        return JSONResponse({"detail": "Servicio no disponible"}, status_code=503)
    return Response(r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))
