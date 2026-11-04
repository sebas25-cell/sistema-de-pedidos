"""Autodiagnóstico: recorre todo el flujo contra el gateway (puerto 8000) y dice qué funciona.

    python probar.py

Requiere los servicios iniciados (iniciar.bat) y haber ejecutado setup_db.py.
OJO: crea datos de prueba (un restaurante "ZZ Prueba", un cliente y algunos pedidos).
"""
import sys
import time

import requests

API = "http://localhost:8000"
ok_n = fail_n = 0


def check(nombre, condicion, extra=""):
    global ok_n, fail_n
    if condicion:
        ok_n += 1
        print(f"  [OK]   {nombre}")
    else:
        fail_n += 1
        print(f"  [FALLA] {nombre} {extra}")


def req(metodo, ruta, token=None, **kw):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.request(metodo, API + ruta, headers=h, timeout=15, **kw)


def login(email, pw):
    r = req("POST", "/usuarios/login", json={"email": email, "password": pw})
    return r.json() if r.status_code == 200 else None


def estado_pedido(tok, pid):
    return req("GET", f"/pedidos/pedidos/{pid}", tok).json()["estado"]


def stock(pid):
    return req("GET", f"/menu/productos/{pid}").json()["stock"]


def msgs(tok, uid, espera=0.6):
    """Avisos del usuario. Los eventos viajan por RabbitMQ (asíncrono), así que se da un instante para que lleguen."""
    time.sleep(espera)
    return [n["mensaje"] for n in req("GET", f"/notificaciones/notificaciones/usuario/{uid}", tok).json()]


print("\n== Servicios")
try:
    est = req("GET", "/estado").json()
except requests.RequestException:
    print("No se pudo conectar al gateway en", API, "- ¿ejecutaste iniciar.bat?")
    sys.exit(1)
check("los 8 servicios responden", est["ok"], str(est["servicios"]))
if not est["ok"]:
    sys.exit(1)

print("\n== Seguridad")
check("sin token no se listan pedidos (401)", req("GET", "/pedidos/pedidos").status_code == 401)
check("token falso rechazado (401)", req("GET", "/pedidos/pedidos", "abc.def.ghi").status_code == 401)
check("login incorrecto (401)", req("POST", "/usuarios/login", json={"email": "x@x.com", "password": "mala"}).status_code == 401)
sufijo = str(int(time.time()))
mail = f"prueba{sufijo}@test.com"
check("registro público crea cliente",
      req("POST", "/usuarios/registro", json={"nombre": "Cliente Prueba", "email": mail, "password": "secreto1"}).status_code == 201)
check("email repetido (409)",
      req("POST", "/usuarios/registro", json={"nombre": "Otro", "email": mail, "password": "secreto1"}).status_code == 409)
cli = login(mail, "secreto1")
adm = login("admin@monteria.com", "admin123")
check("login cliente y admin entregan token", bool(cli and adm and cli.get("token") and adm.get("token")))
if not (cli and adm):
    sys.exit(1)
C, A = cli["token"], adm["token"]
check("cliente NO puede crear restaurantes (403)", req("POST", "/restaurantes/restaurantes", C, json={"nombre": "Hack"}).status_code == 403)
check("cliente NO puede registrar pagos falsos (403)",
      req("POST", "/pagos/pagos", C, json={"pedido_id": 1, "metodo": "TARJETA", "monto": 1}).status_code == 403)
check("cliente NO puede cambiar estados (403)", req("PATCH", "/pedidos/pedidos/1/estado", C, json={"estado": "CONFIRMADO"}).status_code == 403)
check("cliente NO ve usuarios (403)", req("GET", "/usuarios/admin/usuarios", C).status_code == 403)
check("X-Internal-Key falsa no abre nada",
      requests.patch(API + "/menu/productos/1/descontar", json={"cantidad": 1}, headers={"X-Internal-Key": "x"}).status_code in (401, 403))

print("\n== Gestión de restaurantes y menú (admin)")
r = req("POST", "/restaurantes/restaurantes", A, json={"nombre": "ZZ Prueba", "direccion": "Calle de prueba 1", "telefono": "300"})
check("crear restaurante", r.status_code == 201, r.text)
rid = r.json()["id"]
mk = lambda nom, precio, st: req("POST", "/menu/productos", A, json={"restaurante_id": rid, "nombre": nom, "categoria": "Pruebas", "precio": precio, "stock": st})
pa, pb = mk("Plato A", 10000, 5).json()["id"], mk("Plato B", 2500, 3).json()["id"]
check("crear productos", bool(pa and pb))
check("precio inválido rechazado (422)", req("POST", "/menu/productos", A, json={"restaurante_id": rid, "nombre": "x", "precio": -5}).status_code == 422)
check("editar producto", req("PUT", f"/menu/productos/{pb}", A, json={"nombre": "Plato B", "categoria": "Pruebas", "precio": 3000, "stock": 3, "activo": True}).json()["precio"] in (3000, 3000.0))
check("el menú público muestra los productos", {p["id"] for p in req("GET", f"/menu/productos/restaurante/{rid}").json()} >= {pa, pb})
check("reponer stock", req("PATCH", f"/menu/productos/{pa}/reponer", A, json={"cantidad": 5}).status_code == 200 and stock(pa) == 10)

print("\n== Pedidos y pagos")
body = lambda items, metodo="EFECTIVO": {"restaurante_id": rid, "direccion": "Cra 1 #2-3 Montería", "metodo_pago": metodo, "items": items}
r = req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": pa, "cantidad": 2}, {"producto_id": pb, "cantidad": 1}], "TARJETA"))
check("pedido con tarjeta se crea", r.status_code == 201, r.text)
p1 = r.json()["id"]
check("total calculado por el servidor (2x10000 + 3000)", float(r.json()["total"]) == 23000.0, str(r.json()))
check("pago con tarjeta confirma el pedido", r.json()["estado"] == "CONFIRMADO")
check("stock descontado", stock(pa) == 8 and stock(pb) == 2)
m = msgs(C, cli["id"])
check("notificaciones: recibido y confirmado", any("recibido" in x for x in m) and any("confirmado" in x for x in m), str(m))
check("el cliente no puede falsificar el precio (se ignora)",
      req("POST", "/pedidos/pedidos", C, json={**body([{"producto_id": pb, "cantidad": 1}]), "total": 1}).status_code == 201)

r = req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": pa, "cantidad": 1}, {"producto_id": pb, "cantidad": 50}]))
check("sin stock suficiente (409)", r.status_code == 409, r.text)
check("el stock del producto válido se devolvió (sin descuentos huérfanos)", stock(pa) == 8, f"stock A = {stock(pa)}")
check("producto de otro restaurante rechazado (400)",
      req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": 1, "cantidad": 1}])).status_code == 400)
check("dirección vacía rechazada (400)",
      req("POST", "/pedidos/pedidos", C, json={**body([{"producto_id": pa, "cantidad": 1}]), "direccion": "  "}).status_code == 400)

r = req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": pa, "cantidad": 1}, {"producto_id": pa, "cantidad": 1}]))
p2 = r.json()["id"]
check("pedido en efectivo queda CREADO y suma ítems repetidos", r.status_code == 201 and r.json()["estado"] == "CREADO" and float(r.json()["total"]) == 20000.0, r.text)
pagos = req("GET", f"/pagos/pagos/pedido/{p2}", A).json()
check("pago en efectivo PENDIENTE con el monto del pedido", pagos and pagos[0]["estado"] == "PENDIENTE" and float(pagos[0]["monto"]) == 20000.0)

print("\n== Cancelación")
s0 = stock(pa)
check("cliente cancela su pedido", req("POST", f"/pedidos/pedidos/{p2}/cancelar", C).status_code == 200 and estado_pedido(C, p2) == "CANCELADO")
check("stock devuelto al cancelar", stock(pa) == s0 + 2)
check("pago del pedido cancelado queda FALLIDO", req("GET", f"/pagos/pagos/pedido/{p2}", A).json()[0]["estado"] == "FALLIDO")
check("no se puede cancelar dos veces (409)", req("POST", f"/pedidos/pedidos/{p2}/cancelar", C).status_code == 409)
check("un pedido cancelado no avanza (409)", req("PATCH", f"/pedidos/pedidos/{p2}/estado", A, json={"estado": "CONFIRMADO"}).status_code == 409)
otro = req("POST", "/usuarios/registro", json={"nombre": "Otro Cliente", "email": f"otro{sufijo}@test.com", "password": "secreto1"})
O = login(f"otro{sufijo}@test.com", "secreto1")["token"]
check("otro cliente no ve ni cancela pedidos ajenos (403)",
      req("GET", f"/pedidos/pedidos/{p1}", O).status_code == 403 and req("POST", f"/pedidos/pedidos/{p1}/cancelar", O).status_code == 403)
check("el listado del cliente solo incluye lo suyo", all(p["cliente_id"] == cli["id"] for p in req("GET", "/pedidos/pedidos", C).json()))
check("no puede leer notificaciones de otro (403)", req("GET", f"/notificaciones/notificaciones/usuario/{cli['id']}", O).status_code == 403)

print("\n== Disponibilidad del repartidor y pedidos por aceptar")
carlos, laura = login("carlos@monteria.com", "reparto123"), login("laura@monteria.com", "reparto123")
dispo = lambda v, x: req("PATCH", "/usuarios/repartidores/disponibilidad", v["token"], json={"disponible": x}).status_code == 200


def a_listo(pid):
    for e in ("CONFIRMADO", "EN_COCINA", "LISTO"):
        req("PATCH", f"/pedidos/pedidos/{pid}/estado", A, json={"estado": e})
    return req("GET", f"/domicilios/domicilios/pedido/{pid}", A).json()


def nuevo_pedido():
    return req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": pa, "cantidad": 1}])).json()["id"]


def entregar(d, tok):
    for _ in range(2):
        req("PATCH", f"/domicilios/domicilios/{d['id']}/avanzar", tok)


req("PUT", f"/restaurantes/restaurantes/{rid}", A, json={"nombre": "ZZ Prueba", "direccion": "x", "activo": True})
req("PUT", f"/menu/productos/{pb}", A, json={"nombre": "Plato B", "categoria": "Pruebas", "precio": 3000, "stock": 2, "activo": True})
check("el repartidor activa y desactiva su disponibilidad",
      dispo(carlos, True) and req("GET", "/usuarios/repartidores/yo", carlos["token"]).json()["disponible"]
      and dispo(carlos, False) and not req("GET", "/usuarios/repartidores/yo", carlos["token"]).json()["disponible"])
check("un cliente no puede cambiar disponibilidad (403)", req("PATCH", "/usuarios/repartidores/disponibilidad", C, json={"disponible": True}).status_code == 403)
check("el admin ve la disponibilidad de cada repartidor", all("disponible" in x for x in req("GET", "/usuarios/repartidores", A).json()))

dispo(carlos, False); dispo(laura, False)
dA = a_listo(nuevo_pedido())
check("nadie disponible: el pedido listo queda SIN repartidor", dA["repartidor_id"] is None, str(dA))
check("aparece en 'pedidos por aceptar'", any(x["id"] == dA["id"] for x in req("GET", "/domicilios/domicilios/disponibles", carlos["token"]).json()))
check("los repartidores reciben aviso de pedido listo", any("listo para recoger" in x for x in msgs(carlos["token"], carlos["id"])))
check("no disponible: no puede aceptarlo (409)", req("PATCH", f"/domicilios/domicilios/{dA['id']}/aceptar", carlos["token"]).status_code == 409)
check("el cliente no puede aceptar pedidos (403)", req("PATCH", f"/domicilios/domicilios/{dA['id']}/aceptar", C).status_code == 403)
check("el cliente no ve la bolsa de pedidos (403)", req("GET", "/domicilios/domicilios/disponibles", C).status_code == 403)
dispo(carlos, True); dispo(laura, True)
r1 = req("PATCH", f"/domicilios/domicilios/{dA['id']}/aceptar", carlos["token"])
r2 = req("PATCH", f"/domicilios/domicilios/{dA['id']}/aceptar", laura["token"])
check("dos repartidores lo aceptan: solo el primero se lo queda", r1.status_code == 200 and r2.status_code == 409, f"{r1.status_code}/{r2.status_code}")
check("ya no aparece en la lista por aceptar", not any(x["id"] == dA["id"] for x in req("GET", "/domicilios/domicilios/disponibles", laura["token"]).json()))
check("el cliente recibe aviso de que aceptaron su pedido", any("aceptado" in x for x in msgs(C, cli["id"])))

dB = a_listo(nuevo_pedido())
check("con varios disponibles se asigna al que tiene menos domicilios (Laura; Carlos ya tiene uno)", dB["repartidor_id"] == laura["id"], str(dB))
check("el repartidor asignado recibe aviso", any("Nuevo domicilio" in x for x in msgs(laura["token"], laura["id"])))
dispo(laura, False)
dC = a_listo(nuevo_pedido())
check("solo se asigna a repartidores disponibles (Laura apagada -> Carlos)", dC["repartidor_id"] == carlos["id"], str(dC))
dispo(carlos, False)
dD = a_listo(nuevo_pedido())
check("todos apagados: vuelve a la bolsa", dD["repartidor_id"] is None)

# limpieza: se aceptan los pendientes y se entrega todo
dispo(carlos, True); dispo(laura, True)
for x in req("GET", "/domicilios/domicilios/disponibles", carlos["token"]).json():
    req("PATCH", f"/domicilios/domicilios/{x['id']}/aceptar", carlos["token"])
for v in (carlos, laura):
    for x in req("GET", f"/domicilios/domicilios/repartidor/{v['id']}", v["token"]).json():
        entregar(x, v["token"])
check("al entregar todo, los repartidores quedan sin domicilios activos",
      not req("GET", f"/domicilios/domicilios/repartidor/{carlos['id']}", carlos["token"]).json()
      and not req("GET", f"/domicilios/domicilios/repartidor/{laura['id']}", laura["token"]).json())

print("\n== Ciclo completo: cocina -> reparto -> entrega")
dispo(carlos, True); dispo(laura, True)
r = req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": pa, "cantidad": 1}]))
p3 = r.json()["id"]
check("admin confirma", req("PATCH", f"/pedidos/pedidos/{p3}/estado", A, json={"estado": "CONFIRMADO"}).status_code == 200)
check("no se puede saltar estados (409)", req("PATCH", f"/pedidos/pedidos/{p3}/estado", A, json={"estado": "LISTO"}).status_code == 409)
check("a cocina", req("PATCH", f"/pedidos/pedidos/{p3}/estado", A, json={"estado": "EN_COCINA"}).status_code == 200)
check("el cliente ya no puede cancelar en cocina (409)", req("POST", f"/pedidos/pedidos/{p3}/cancelar", C).status_code == 409)
check("listo", req("PATCH", f"/pedidos/pedidos/{p3}/estado", A, json={"estado": "LISTO"}).status_code == 200)
check("admin NO puede forzar EN_CAMINO (lo hace el repartidor) (403)",
      req("PATCH", f"/pedidos/pedidos/{p3}/estado", A, json={"estado": "EN_CAMINO"}).status_code == 403)
dom = req("GET", f"/domicilios/domicilios/pedido/{p3}", A)
check("se creó el domicilio con repartidor asignado", dom.status_code == 200 and dom.json()["repartidor_id"], dom.text)
d = dom.json()
reps = {"carlos@monteria.com": carlos, "laura@monteria.com": laura}
dueno = next(v for v in reps.values() if v["id"] == d["repartidor_id"])
ajeno = next(v for v in reps.values() if v["id"] != d["repartidor_id"])
check("el cliente recibió aviso del repartidor", any("repartidor" in x for x in msgs(C, cli["id"])))
check("otro repartidor NO puede mover ese domicilio (403)", req("PATCH", f"/domicilios/domicilios/{d['id']}/avanzar", ajeno["token"]).status_code == 403)
check("el cliente NO puede mover domicilios (403)", req("PATCH", f"/domicilios/domicilios/{d['id']}/avanzar", C).status_code == 403)
check("el repartidor ve su domicilio", any(x["id"] == d["id"] for x in req("GET", f"/domicilios/domicilios/repartidor/{dueno['id']}", dueno["token"]).json()))
check("repartidor sale a ruta -> pedido EN_CAMINO", req("PATCH", f"/domicilios/domicilios/{d['id']}/avanzar", dueno["token"]).status_code == 200 and estado_pedido(A, p3) == "EN_CAMINO")
check("un pedido en camino ya no se cancela (409)", req("POST", f"/pedidos/pedidos/{p3}/cancelar", A).status_code == 409)
check("repartidor entrega -> pedido ENTREGADO", req("PATCH", f"/domicilios/domicilios/{d['id']}/avanzar", dueno["token"]).status_code == 200 and estado_pedido(A, p3) == "ENTREGADO")
check("al entregar, el efectivo queda PAGADO", req("GET", f"/pagos/pagos/pedido/{p3}", A).json()[0]["estado"] == "PAGADO")
check("ya entregado no avanza (409)", req("PATCH", f"/domicilios/domicilios/{d['id']}/avanzar", dueno["token"]).status_code == 409)
m = msgs(C, cli["id"])
check("notificaciones con emoji guardadas", any("🛵" in x for x in m) and any("🔥" in x for x in m), str(m[:4]))

print("\n== Reasignar repartidor y cancelar pedido LISTO (admin)")
r = req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": pa, "cantidad": 1}]))
p4 = r.json()["id"]
for e in ("CONFIRMADO", "EN_COCINA", "LISTO"):
    req("PATCH", f"/pedidos/pedidos/{p4}/estado", A, json={"estado": e})
d4 = req("GET", f"/domicilios/domicilios/pedido/{p4}", A).json()
nuevo = ajeno if d4["repartidor_id"] == dueno["id"] else dueno
check("admin reasigna repartidor", req("PATCH", f"/domicilios/domicilios/{d4['id']}/asignar", A, json={"repartidor_id": nuevo["id"]}).status_code == 200
      and req("GET", f"/domicilios/domicilios/pedido/{p4}", A).json()["repartidor_id"] == nuevo["id"])
s0 = stock(pa)
check("admin cancela un pedido LISTO", req("POST", f"/pedidos/pedidos/{p4}/cancelar", A).status_code == 200 and stock(pa) == s0 + 1)
check("se eliminó su domicilio", req("GET", f"/domicilios/domicilios/pedido/{p4}", A).status_code == 404)

print("\n== Restaurante / producto desactivados")
req("PUT", f"/menu/productos/{pb}", A, json={"nombre": "Plato B", "categoria": "Pruebas", "precio": 3000, "stock": 2, "activo": False})
check("producto oculto no se muestra en el menú", pb not in [p["id"] for p in req("GET", f"/menu/productos/restaurante/{rid}").json()])
check("producto oculto no se puede pedir (409)", req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": pb, "cantidad": 1}])).status_code == 409)
req("DELETE", f"/restaurantes/restaurantes/{rid}", A)
check("restaurante inactivo no aparece en la lista pública", rid not in [x["id"] for x in req("GET", "/restaurantes/restaurantes").json()])
check("restaurante inactivo no recibe pedidos (409)", req("POST", "/pedidos/pedidos", C, json=body([{"producto_id": pa, "cantidad": 1}])).status_code == 409)

print("\n== Panel admin")
res = req("GET", "/pedidos/pedidos/resumen", A).json()
check("resumen de pedidos", {"activos", "entregados_hoy", "cancelados_hoy"} <= set(res), str(res))
check("admin crea repartidor", req("POST", "/usuarios/admin/usuarios", A, json={"nombre": "Nuevo Repartidor", "email": f"rep{sufijo}@test.com", "password": "reparto1", "rol": "REPARTIDOR"}).status_code == 201)

print("\n== Monitoreo, trazabilidad y documentación")
mon = req("GET", "/monitor", A)
check("/monitor (ADMIN) devuelve el estado de los 8 servicios", mon.status_code == 200 and len(mon.json()["servicios"]) == 8, mon.text[:200])
check("/monitor está protegido: el cliente no entra (403)", req("GET", "/monitor", C).status_code == 403)
check("/metrics de un servicio exige ADMIN (403 al cliente)", req("GET", "/pedidos/metrics", C).status_code == 403)
serv = {x["nombre"]: x for x in mon.json()["servicios"]} if mon.status_code == 200 else {}
check("las métricas cuentan peticiones y latencia", serv.get("pedidos", {}).get("metricas", {}).get("peticiones", 0) > 0)
broker = serv.get("notificaciones", {}).get("metricas", {}).get("broker", "?")
print(f"         (modo de mensajería detectado: {broker})")
check("el consumidor de eventos está operativo (RabbitMQ conectado o HTTP directo)", broker == "conectado" or broker.startswith("sin configurar"), broker)
rid = "traza-" + sufijo
r = requests.get(API + "/restaurantes/restaurantes", headers={"X-Request-ID": rid}, timeout=15)
check("el X-Request-ID viaja por el gateway y vuelve en la respuesta", r.headers.get("X-Request-ID") == rid, str(r.headers.get("X-Request-ID")))
check("cada respuesta lleva un X-Request-ID aunque no se envíe", bool(requests.get(API + "/restaurantes/restaurantes", timeout=15).headers.get("X-Request-ID")))
r = req("POST", "/notificaciones/eventos", C, json={"id": "x", "tipo": "pedido.estado_cambiado", "datos": {}})
check("el cliente NO puede inyectar eventos (403)", r.status_code == 403)
spec = requests.get(API + "/openapi.json", timeout=15).json()
ops = [(r_, m_) for r_, p_ in spec["paths"].items() for m_, o_ in p_.items() if isinstance(o_, dict)]
check("Swagger unificado: 50+ operaciones, todas con resumen", len(ops) >= 50 and all(spec["paths"][r_][m_].get("summary") for r_, m_ in ops), str(len(ops)))
check("Swagger declara el esquema de seguridad Bearer JWT", "HTTPBearer" in spec["components"]["securitySchemes"])
check("Swagger UI disponible en /docs", requests.get(API + "/docs", timeout=15).status_code == 200)
check("error 404 en formato JSON {detail}", "detail" in req("GET", "/pedidos/pedidos/99999999", A).json())
check("error 422 de validación (cuerpo inválido)", req("POST", "/usuarios/login", json={"email": 5}).status_code == 422)

print(f"\nResultado: {ok_n} correctas, {fail_n} con falla")
sys.exit(1 if fail_n else 0)
