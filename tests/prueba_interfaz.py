import requests, time, sys
from playwright.sync_api import sync_playwright
API="http://localhost:8000"; WEB="http://localhost:3000"; OUT="/home/claude/sistema_4.0/docs/evidencias/capturas/"
def lg(e,p): return requests.post(API+"/usuarios/login",json={"email":e,"password":p}).json()
car=lg("carlos@monteria.com","reparto123")
requests.patch(API+"/usuarios/repartidores/disponibilidad",json={"disponible":True},headers={"Authorization":"Bearer "+car["token"]})
errs=[]; ok=True
def check(n,c):
    global ok; ok&=bool(c); print(("[OK]    " if c else "[FALLA] ")+n)
with sync_playwright() as pw:
    b=pw.chromium.launch(); 
    ctx=b.new_context(viewport={"width":1366,"height":850}); pg=ctx.new_page()
    pg.on("console",lambda m: errs.append(m.text) if m.type=="error" else None); pg.on("pageerror",lambda e: errs.append(str(e)))
    pg.goto(WEB+"/index.html"); pg.screenshot(path=OUT+"01_cliente_acceso.png")
    pg.click(".demo"); pg.click("text=Ingresar"); pg.wait_for_selector(".prod")
    check("cliente: restaurantes y menú cargan", pg.locator(".rest").count()>=1 and pg.locator(".prod").count()>=1)
    pg.fill("#buscar","zzzz"); check("búsqueda sin resultados", "No encontramos" in pg.inner_text("#menu")); pg.fill("#buscar","")
    pg.locator(".prod .qty .p").nth(0).click(); pg.locator(".prod .qty .p").nth(0).click(); pg.locator(".prod .qty .p").nth(1).click()
    check("badge del carrito = 3", pg.inner_text("#cBadge")=="3")
    pg.screenshot(path=OUT+"02_cliente_menu.png",full_page=False)
    pg.click("#btnCarrito"); pg.fill("#direccion","Cra 5 #20-10, Montería"); pg.click("label:has-text('Nequi')")
    pg.wait_for_timeout(400); pg.screenshot(path=OUT+"03_cliente_carrito.png")
    pg.click("#btnPedir"); pg.wait_for_selector("#trackTitulo:has-text('Pedido #')")
    pid=int(pg.inner_text("#trackTitulo").split("#")[1].split()[0]); check(f"pedido #{pid} creado desde la UI", pid>0)
    time.sleep(1.5)
    # personal
    ap=ctx.new_page(); ap.on("console",lambda m: errs.append(m.text) if m.type=="error" else None); ap.on("pageerror",lambda e: errs.append(str(e)))
    ap.goto(WEB+"/admin.html"); ap.fill("#email","admin@monteria.com"); ap.fill("#password","admin123"); ap.click("text=Ingresar")
    ap.wait_for_selector(f".ped:has-text('#{pid}')")
    for accion in ["Pasar a cocina","Marcar listo"]:
        ap.locator(f".ped:has-text('#{pid}') .go").click(); ap.wait_for_timeout(1300)
    ap.wait_for_timeout(1500); ap.screenshot(path=OUT+"04_admin_tablero.png")
    check("admin: pedido llegó a LISTO con repartidor", ap.locator(f".col:has-text('Listos') .ped:has-text('#{pid}')").count()==1 and "Carlos" in ap.inner_text(f".ped:has-text('#{pid}')"))
    ap.locator(f".ped:has-text('#{pid}') .go").click(); ap.wait_for_timeout(1300)
    ap.locator(f".ped:has-text('#{pid}') .go").click(); ap.wait_for_timeout(1500)
    pg.bring_to_front(); pg.wait_for_timeout(3500); pg.screenshot(path=OUT+"05_cliente_seguimiento.png",full_page=True)
    check("cliente: seguimiento llega a Entregado", pg.locator(".step.on:has-text('Entregado')").count()==1)
    check("cliente: campana con avisos sin leer", int(pg.inner_text("#nBadge") or 0)>=3)
    pg.click("#btnCampana"); pg.wait_for_timeout(600); pg.screenshot(path=OUT+"06_cliente_notificaciones.png")
    pg.wait_for_timeout(2500); check("al abrir la campana los avisos quedan leídos", pg.locator("#nBadge.hide").count()==1)
    # tema claro
    pg.keyboard.press("Escape"); pg.click("#btnTema"); pg.wait_for_timeout(300); pg.screenshot(path=OUT+"07_cliente_tema_claro.png")
    # repartidor
    rp=ctx.new_page(); rp.on("pageerror",lambda e: errs.append(str(e)))
    rp.goto(WEB+"/admin.html"); rp.evaluate("localStorage.removeItem('staff')"); rp.reload()
    rp.fill("#email","carlos@monteria.com"); rp.fill("#password","reparto123"); rp.click("text=Ingresar"); rp.wait_for_selector("#dispTexto")
    rp.wait_for_timeout(1200); rp.screenshot(path=OUT+"08_repartidor.png")
    check("repartidor: ve su estado de disponibilidad", "DISPONIBLE" in rp.inner_text("#dispTexto"))
    # monitor
    mp=ctx.new_page(); mp.on("pageerror",lambda e: errs.append(str(e)))
    mp.goto(WEB+"/monitor.html"); mp.fill("#password","admin123"); mp.click("text=Ingresar"); mp.wait_for_selector(".tile"); mp.wait_for_timeout(800)
    mp.screenshot(path=OUT+"09_monitor.png",full_page=True)
    check("monitor: 8 servicios y broker conectado", mp.locator(".tile").count()==8 and "conectado" in mp.inner_text("#broker"))
    # móvil
    mv=b.new_context(viewport={"width":390,"height":844},device_scale_factor=2).new_page(); mv.on("pageerror",lambda e: errs.append(str(e)))
    mv.goto(WEB+"/index.html"); mv.evaluate("localStorage.setItem('tema','dark')"); mv.reload(); mv.click(".demo"); mv.click("text=Ingresar"); mv.wait_for_selector(".prod")
    mv.screenshot(path=OUT+"10_movil_menu.png")
    check("móvil: sin desbordamiento horizontal", mv.evaluate("document.documentElement.scrollWidth<=window.innerWidth+1"))
    b.close()
errs=[e for e in errs if "ERR_TUNNEL" not in e and "ERR_NAME" not in e]  # fuentes de Google bloqueadas en el sandbox
check("sin errores de consola/JS: "+str(errs[:3]), not errs)
print("RESULTADO:", "TODO OK" if ok else "HAY FALLAS"); sys.exit(0 if ok else 1)
