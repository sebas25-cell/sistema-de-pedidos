"""Logs, identificador de petición y métricas en memoria para cada microservicio.

* Cada petición recibe un X-Request-ID (o conserva el que trae). Ese mismo id viaja en las llamadas
  entre servicios y aparece en todos los logs, así se puede seguir un pedido a través de los 8 servicios.
* Los logs salen por consola y a `logs/<servicio>.log` (rotativo). LOG_FORMAT=json los emite en JSON.
* Las métricas (peticiones, errores, latencia, rutas más usadas, últimos errores) se consultan en /metrics.
"""
import contextvars
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import deque
from logging.handlers import RotatingFileHandler

request_id_var = contextvars.ContextVar("request_id", default="-")
_configurado = False


class _FiltroRid(logging.Filter):
    def filter(self, record):
        record.rid = request_id_var.get()
        return True


class _FormatoJson(logging.Formatter):
    def format(self, record):
        d = {"ts": self.formatTime(record), "nivel": record.levelname, "servicio": record.name.split(".")[-1],
             "request_id": getattr(record, "rid", "-"), "mensaje": record.getMessage()}
        if record.exc_info:
            d["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(d, ensure_ascii=False)


class AnilloLogs(logging.Handler):
    """Guarda en memoria los últimos avisos y errores para mostrarlos en el panel de monitoreo."""

    def __init__(self, capacidad=50):
        super().__init__(level=logging.WARNING)
        self.registros = deque(maxlen=capacidad)

    def emit(self, record):
        self.registros.append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "nivel": record.levelname, "mensaje": record.getMessage()[:300], "rid": getattr(record, "rid", "-"),
        })


anillo = AnilloLogs()


def configurar_logging(servicio):
    """Configura el logger 'app' (una sola vez por proceso) y devuelve el logger del servicio."""
    global _configurado
    raiz = logging.getLogger("app")
    if not _configurado:
        _configurado = True
        raiz.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
        raiz.propagate = False
        if os.getenv("LOG_FORMAT", "").lower() == "json":
            formato = _FormatoJson()
        else:
            formato = logging.Formatter(f"%(asctime)s %(levelname)-7s {servicio:<14} [%(rid)s] %(message)s")
        manejadores = [logging.StreamHandler(sys.stdout), anillo]
        try:
            carpeta = os.getenv("LOG_DIR", "logs")
            os.makedirs(carpeta, exist_ok=True)
            manejadores.append(RotatingFileHandler(os.path.join(carpeta, f"{servicio}.log"),
                                                   maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
        except OSError:
            pass  # sin permiso de escritura: se sigue solo con la consola
        for m in manejadores:
            m.setFormatter(formato)
            m.addFilter(_FiltroRid())
            raiz.addHandler(m)
    return logging.getLogger(f"app.{servicio}")


class Metricas:
    def __init__(self, servicio):
        self.servicio = servicio
        self.inicio = time.time()
        self._lock = threading.Lock()
        self.total = 0
        self.clases = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        self._lat_total = 0.0
        self._muestras = deque(maxlen=300)
        self._rutas = {}
        self.errores = deque(maxlen=20)
        self._proveedores = []

    def agregar_proveedor(self, funcion):
        """Registra una función que aporta datos extra al snapshot (p. ej. estado del broker)."""
        self._proveedores.append(funcion)

    def registrar(self, metodo, ruta, status, ms, rid):
        with self._lock:
            self.total += 1
            self.clases[f"{status // 100}xx"] = self.clases.get(f"{status // 100}xx", 0) + 1
            self._lat_total += ms
            self._muestras.append(ms)
            r = self._rutas.setdefault(f"{metodo} {ruta}", [0, 0.0, 0])
            r[0] += 1
            r[1] += ms
            if status >= 500:
                r[2] += 1
                self.errores.append({"ts": time.strftime("%H:%M:%S"), "ruta": f"{metodo} {ruta}",
                                     "status": status, "ms": round(ms, 1), "rid": rid})

    def snapshot(self):
        with self._lock:
            m = sorted(self._muestras)
            p95 = m[int(len(m) * 0.95) - 1] if len(m) >= 2 else (m[0] if m else 0)
            top = sorted(self._rutas.items(), key=lambda kv: kv[1][0], reverse=True)[:8]
            datos = {
                "servicio": self.servicio,
                "uptime_s": int(time.time() - self.inicio),
                "peticiones": self.total,
                "por_clase": dict(self.clases),
                "latencia_media_ms": round(self._lat_total / self.total, 1) if self.total else 0,
                "latencia_p95_ms": round(p95, 1),
                "rutas_top": [{"ruta": k, "n": v[0], "ms_medio": round(v[1] / v[0], 1), "errores": v[2]} for k, v in top],
                "errores_recientes": list(self.errores),
                "logs_recientes": list(anillo.registros)[-15:],
            }
        for f in self._proveedores:
            try:
                datos.update(f())
            except Exception:
                pass
        return datos


def instalar(app, servicio):
    """Añade el middleware de logs + métricas + X-Request-ID y devuelve el objeto de métricas."""
    log = configurar_logging(servicio)
    metricas = Metricas(servicio)

    @app.middleware("http")
    async def registro(request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.rid = rid
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            ms = (time.perf_counter() - t0) * 1000
            ruta = request.url.path
            log.error("%s %s -> 500 (%.1f ms) excepción no controlada", request.method, ruta, ms, exc_info=True)
            metricas.registrar(request.method, ruta, 500, ms, rid)
            request_id_var.reset(token)
            raise
        ms = (time.perf_counter() - t0) * 1000
        route = request.scope.get("route")
        ruta = getattr(route, "path", request.url.path)       # plantilla (/pedidos/{pid}), no el id concreto
        response.headers["X-Request-ID"] = rid
        if ruta not in ("/health", "/metrics"):
            nivel = logging.ERROR if response.status_code >= 500 else logging.WARNING if response.status_code >= 400 else logging.INFO
            log.log(nivel, "%s %s -> %s (%.1f ms)", request.method, request.url.path, response.status_code, ms)
            metricas.registrar(request.method, ruta, response.status_code, ms, rid)
        request_id_var.reset(token)
        return response

    app.state.metricas = metricas
    return metricas
