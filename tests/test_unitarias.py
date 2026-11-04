"""Pruebas unitarias (sin base de datos ni servicios levantados).  Ejecutar:  python -m pytest tests -q"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jwt, pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from common import auth, config, mensajeria, observabilidad
from common.auth import crear_token, requiere, SECRET, INTERNAL_KEY
from common.openapi_unificado import unir

U = {"id": 7, "rol": "CLIENTE", "nombre": "Ana"}

def _app():
    a = FastAPI(); observabilidad.instalar(a, "prueba")
    @a.get("/admin")
    def admin(u=Depends(requiere("ADMIN"))): return u
    @a.get("/interno")
    def interno(u=Depends(requiere())): return u
    @a.get("/cliente")
    def cliente(u=Depends(requiere("CLIENTE"))): return u
    return TestClient(a)

def test_token_contiene_datos_y_vence_en_12h():
    d = jwt.decode(crear_token(U), SECRET, algorithms=["HS256"])
    assert d["sub"] == "7" and d["rol"] == "CLIENTE" and 11.9*3600 < d["exp"]-time.time() <= 12*3600

def test_sin_token_401():           assert _app().get("/cliente").status_code == 401
def test_token_alterado_401():
    t = crear_token(U)[:-3] + "abc"
    assert _app().get("/cliente", headers={"Authorization": "Bearer "+t}).status_code == 401
def test_token_vencido_401():
    t = jwt.encode({"sub": "1", "rol": "ADMIN", "exp": int(time.time())-5}, SECRET, algorithm="HS256")
    assert _app().get("/admin", headers={"Authorization": "Bearer "+t}).status_code == 401
def test_rol_incorrecto_403():
    assert _app().get("/admin", headers={"Authorization": "Bearer "+crear_token(U)}).status_code == 403
def test_rol_correcto_200():
    assert _app().get("/cliente", headers={"Authorization": "Bearer "+crear_token(U)}).status_code == 200
def test_clave_interna_pasa_como_sistema():
    r = _app().get("/admin", headers={"X-Internal-Key": INTERNAL_KEY}); assert r.status_code == 200 and r.json()["rol"] == "SISTEMA"
def test_clave_interna_incorrecta_rechazada():
    assert _app().get("/admin", headers={"X-Internal-Key": "x"}).status_code == 401
def test_requiere_vacio_solo_interno():
    c = _app(); assert c.get("/interno", headers={"Authorization": "Bearer "+crear_token(U)}).status_code == 403
    assert c.get("/interno", headers={"X-Internal-Key": INTERNAL_KEY}).status_code == 200

def test_request_id_se_conserva_y_se_genera():
    c = _app()
    assert c.get("/cliente", headers={"X-Request-ID": "abc123"}).headers["x-request-id"] == "abc123"
    assert len(c.get("/cliente").headers["x-request-id"]) >= 8

def test_metricas_cuentan_por_clase_y_ruta():
    a = FastAPI(); m = observabilidad.instalar(a, "p")
    @a.get("/x/{i}")
    def x(i: int): return {}
    c = TestClient(a); c.get("/x/1"); c.get("/x/2"); c.get("/x/abc"); c.get("/nada")
    s = m.snapshot(); assert s["peticiones"] == 4 and s["por_clase"]["2xx"] == 2 and s["por_clase"]["4xx"] == 2
    assert any(r["ruta"] == "GET /x/{i}" and r["n"] == 3 for r in s["rutas_top"])

def test_url_de_servicio_por_entorno(monkeypatch):
    assert config.url("menu") == "http://127.0.0.1:8003"
    monkeypatch.setenv("MENU_URL", "http://menu:8003/"); assert config.url("menu") == "http://menu:8003"

def test_publicar_sin_broker_usa_http(monkeypatch):
    llamadas = []
    class R: status_code = 200
    monkeypatch.setattr(config, "RABBITMQ_URL", "")
    monkeypatch.setattr(mensajeria, "llamar", lambda m, u, **k: llamadas.append((m, u, k["json"])) or R())
    assert mensajeria.publicar("pedido.estado_cambiado", {"pedido_id": 1}) == "http"
    assert llamadas[0][1].endswith("/eventos") and llamadas[0][2]["tipo"] == "pedido.estado_cambiado" and llamadas[0][2]["id"]

def test_publicar_sin_ningun_medio_devuelve_none(monkeypatch):
    monkeypatch.setattr(config, "RABBITMQ_URL", ""); monkeypatch.setattr(mensajeria, "llamar", lambda *a, **k: None)
    assert mensajeria.publicar("pedido.x", {}) is None

def test_publicar_con_broker_caido_activa_circuito(monkeypatch):
    class R: status_code = 201
    monkeypatch.setattr(config, "RABBITMQ_URL", "amqp://u:p@127.0.0.1:1/%2F"); monkeypatch.setattr(mensajeria, "_sin_broker_hasta", 0.0)
    monkeypatch.setattr(mensajeria, "llamar", lambda *a, **k: R())
    assert mensajeria.publicar("pedido.x", {}) == "http" and mensajeria._sin_broker_hasta > time.time()

def test_openapi_unificado_prefija_rutas():
    spec = lambda p: {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {p: {"get": {"responses": {"200": {"description": "ok"}}}}}, "components": {"schemas": {}}}
    u = unir({"menu": spec("/productos"), "pedidos": spec("/pedidos")}, "http://localhost:8000", [])
    assert "/menu/productos" in u["paths"] and "/pedidos/pedidos" in u["paths"]
