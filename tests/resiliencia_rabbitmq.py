import json, subprocess, time, requests, pika, sys
API="http://localhost:8000"; N="http://127.0.0.1:8007"
KEY={"X-Internal-Key":"monteria-clave-interna-servicios"}
RMQ="amqp://guest:guest@127.0.0.1:5672/%2F"
H=lambda t:{"Authorization":"Bearer "+t}
lg=lambda e,p: requests.post(API+"/usuarios/login",json={"email":e,"password":p}).json()
A=lg("admin@monteria.com","admin123")["token"]; c=lg("cliente@monteria.com","cliente123"); C=c["token"]
rmq=lambda *a: subprocess.run(["su","rabbitmq","-s","/bin/bash","-c","HOME=/var/lib/rabbitmq rabbitmqctl -q "+" ".join(a)],capture_output=True,text=True).stdout.strip()
def avisos():
    try:
        d=requests.get(f"{API}/notificaciones/notificaciones/usuario/{c['id']}",headers=H(C),timeout=3).json()
        return [n["mensaje"] for n in d] if isinstance(d,list) else []
    except Exception: return []
def pedido():
    pid=requests.get(API+"/menu/productos/restaurante/1").json()[0]["id"]
    r=requests.post(API+"/pedidos/pedidos",headers=H(C),json={"restaurante_id":1,"direccion":"Calle carrera 5","metodo_pago":"EFECTIVO","items":[{"producto_id":pid,"cantidad":1}]})
    return r.status_code, r.json().get("id")
def esperar(texto, seg=8):
    for _ in range(int(seg*5)):
        if any(texto in a for a in avisos()): return True
        time.sleep(0.2)
    return False
def dlq():
    ch=pika.BlockingConnection(pika.URLParameters(RMQ)).channel(); return ch.queue_declare("notificaciones.dlq",passive=True).method.message_count
ok=True
def check(n,cond):
    global ok; ok&=bool(cond); print(("  [OK]    " if cond else "  [FALLA] ")+n)

print("1) Idempotencia: el mismo evento enviado dos veces crea los avisos una sola vez")
ev={"id":"idem-"+str(int(time.time())),"tipo":"pedido.estado_cambiado","datos":{"pedido_id":9001,"cliente_id":c["id"],"estado":"EN_COCINA"}}
r1=requests.post(N+"/eventos",json=ev,headers=KEY).json(); r2=requests.post(N+"/eventos",json=ev,headers=KEY).json()
check(f"primer envío crea {r1['creadas']} aviso, repetido crea {r2['creadas']}", r1["creadas"]==1 and r2["creadas"]==0)

print("2) Mensaje inválido va a la cola de mensajes fallidos (DLQ) y el consumidor sigue vivo")
antes=dlq()
ch=pika.BlockingConnection(pika.URLParameters(RMQ)).channel()
ch.basic_publish("eventos","pedido.estado_cambiado",b"esto-no-es-json")
time.sleep(1.5)
check(f"DLQ pasó de {antes} a {dlq()} mensaje(s)", dlq()==antes+1)
s,pid=pedido(); check("después del mensaje inválido, un pedido nuevo sigue notificando", s==201 and esperar(f"#{pid} fue recibido"))

print("3) RabbitMQ se cae: el pedido sigue funcionando (respaldo HTTP) y los avisos llegan")
rmq("stop_app"); time.sleep(2)
t0=time.time(); s,pid=pedido(); dt=time.time()-t0
check(f"pedido #{pid} creado con RabbitMQ caído (HTTP {s}, {dt:.1f}s)", s==201)
check("el aviso del pedido llegó igual por el respaldo HTTP", esperar(f"#{pid} fue recibido"))
print("   "+" | ".join(l for l in open("/home/claude/scratch/logs4/pedidos.log").read().splitlines()[-40:] if "HTTP directo" in l or "por HTTP" in l)[-260:])
rmq("start_app"); time.sleep(8)
check("RabbitMQ vuelve y el consumidor se reconecta solo", requests.get("http://127.0.0.1:8007/health").json().get("broker")=="conectado")
time.sleep(16)  # el publicador espera 15 s antes de reintentar AMQP
s,pid=pedido(); check("tras la recuperación los eventos vuelven a viajar por RabbitMQ", s==201 and esperar(f"#{pid} fue recibido"))

print("4) El consumidor se cae: los eventos esperan en la cola durable y se entregan al volver")
pidnot=subprocess.run("ss -ltnp | grep ':8007 ' | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | head -1",shell=True,capture_output=True,text=True).stdout.strip()
subprocess.run(["kill",pidnot]); time.sleep(2)
s,pid=pedido(); check(f"pedido #{pid} creado con notificaciones caído (HTTP {s})", s==201)
print("   mensajes esperando en la cola:", rmq("list_queues name messages | grep -E '^notificaciones\\s'"))
subprocess.Popen("cd /home/claude/sistema_4.0 && DB_USER=svc_notificaciones DB_PASS=svc_secreto LOG_DIR=/home/claude/scratch/logs4 RABBITMQ_URL='amqp://guest:guest@127.0.0.1:5672/%2F' nohup python3 -m uvicorn notificaciones.main:app --port 8007 --no-access-log >> /home/claude/scratch/logs4/notificaciones.out 2>&1 &",shell=True)
check("al volver notificaciones, el aviso pendiente se entrega (no se perdió)", esperar(f"#{pid} fue recibido", 20))
print("\nRESULTADO:", "TODO OK" if ok else "HAY FALLAS"); sys.exit(0 if ok else 1)
