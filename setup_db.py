"""Prepara las bases de datos en el MySQL/MariaDB de XAMPP.

    python setup_db.py            crea lo que falte, actualiza tablas viejas y agrega datos de demostración
    python setup_db.py --reset    BORRA las 7 bases y las crea de cero (pierdes todos los datos)

Es seguro ejecutarlo varias veces. Usa las variables DB_HOST, DB_PORT, DB_USER y DB_PASS
(por defecto 127.0.0.1:3306, root, sin contraseña, igual que XAMPP).
"""
import os
import re
import sys

import bcrypt
import pymysql

BASES = ["db_usuarios", "db_restaurantes", "db_menu", "db_pedidos", "db_pagos", "db_domicilios", "db_notificaciones"]
COLLATION = "utf8mb4_unicode_ci"

# (base, tabla, columna, definición). Si la columna no existe se agrega; si existe se ajusta su tipo.
AJUSTES = [
    ("db_usuarios", "usuarios", "rol", "VARCHAR(20) NOT NULL DEFAULT 'CLIENTE'"),
    ("db_usuarios", "usuarios", "disponible", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("db_restaurantes", "restaurantes", "telefono", "VARCHAR(30) NULL"),
    ("db_restaurantes", "restaurantes", "activo", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("db_menu", "productos", "categoria", "VARCHAR(50) NULL"),
    ("db_menu", "productos", "activo", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("db_pedidos", "pedidos", "estado", "VARCHAR(20) NOT NULL DEFAULT 'CREADO'"),
    ("db_pedidos", "pedidos", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ("db_pedidos", "detalle_pedido", "nombre", "VARCHAR(100) NULL"),
    ("db_pagos", "pagos", "estado", "VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE'"),
    ("db_domicilios", "domicilios", "repartidor_id", "INT NULL"),
    ("db_domicilios", "domicilios", "estado", "VARCHAR(20) NOT NULL DEFAULT 'ASIGNADO'"),
    ("db_notificaciones", "notificaciones", "leido", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("db_notificaciones", "notificaciones", "evento_id", "VARCHAR(40) NULL"),
]

# Usuario de MySQL de cada microservicio (solo se crean si defines SERVICE_DB_PASS, como hace docker-compose).
# Cada uno tiene permisos de datos SOLO sobre su propia base: así un servicio no puede leer las tablas de otro.
USUARIOS_SERVICIO = {
    "usuarios": "db_usuarios", "restaurantes": "db_restaurantes", "menu": "db_menu", "pedidos": "db_pedidos",
    "pagos": "db_pagos", "domicilios": "db_domicilios", "notificaciones": "db_notificaciones",
}

USUARIOS_DEMO = [
    ("Administrador", "admin@monteria.com", "admin123", "ADMIN"),
    ("Carlos Repartidor", "carlos@monteria.com", "reparto123", "REPARTIDOR"),
    ("Laura Repartidora", "laura@monteria.com", "reparto123", "REPARTIDOR"),
    ("Cliente Demo", "cliente@monteria.com", "cliente123", "CLIENTE"),
]

RESTAURANTES_DEMO = [
    ("Burger del Sinú", "Calle 27 #3-45, Montería", "3001234567", [
        ("Hamburguesa Clásica", "Hamburguesas", 18000, 40), ("Hamburguesa Doble Queso", "Hamburguesas", 24000, 40),
        ("Hamburguesa de Pollo", "Hamburguesas", 20000, 30), ("Papas Fritas", "Acompañamientos", 7000, 60),
        ("Aros de Cebolla", "Acompañamientos", 8000, 40), ("Gaseosa 400 ml", "Bebidas", 4000, 100),
        ("Jugo de Mango", "Bebidas", 6000, 50), ("Brownie con Helado", "Postres", 9000, 25)]),
    ("Pizzería La Ceiba", "Av. Primera #41-20, Montería", "3109876543", [
        ("Pizza Margarita", "Pizzas", 32000, 25), ("Pizza Hawaiana", "Pizzas", 36000, 25),
        ("Pizza Pepperoni", "Pizzas", 38000, 25), ("Pan de Ajo", "Entradas", 9000, 40),
        ("Alitas BBQ", "Entradas", 16000, 30), ("Limonada de Coco", "Bebidas", 8000, 60),
        ("Cerveza Águila", "Bebidas", 5000, 80)]),
    ("Sabor Costeño", "Cra. 6 #32-10, Montería", "3205550101", [
        ("Arroz con Coco y Pescado Frito", "Platos", 28000, 20), ("Mote de Queso", "Sopas", 15000, 20),
        ("Bandeja Montería", "Platos", 30000, 15), ("Arepa de Huevo", "Entradas", 5000, 50),
        ("Pollo Asado 1/4", "Pollo", 17000, 30), ("Limonada Natural", "Bebidas", 5000, 60),
        ("Postre de Natas", "Postres", 7000, 20)]),
]


def conectar(db=None):
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"), password=os.getenv("DB_PASS", ""),
        database=db, charset="utf8mb4", connect_timeout=5, autocommit=True,
    )


def sentencias(ruta):
    sql = open(ruta, encoding="utf-8").read()
    sql = re.sub(r"--[^\n]*", "", sql)          # quita comentarios
    return [s.strip() for s in sql.split(";") if s.strip()]


def existe_tabla(c, db, tabla):
    c.execute("SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (db, tabla))
    return c.fetchone() is not None


def existe_columna(c, db, tabla, col):
    c.execute("SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
              (db, tabla, col))
    return c.fetchone() is not None


def aviso(msg):
    print("   (!) " + msg)


def main():
    try:
        sys.stdout.reconfigure(errors="replace")   # evita errores de tildes en consolas antiguas
    except Exception:
        pass
    reset = "--reset" in sys.argv
    try:
        conn = conectar()
    except pymysql.err.OperationalError as e:
        codigo = e.args[0] if e.args else 0
        if codigo == 1045:
            print("\nMySQL rechazó el usuario/contraseña (usuario '%s')." % os.getenv("DB_USER", "root"))
            print("-> Si root tiene contraseña en tu XAMPP, ejecuta antes:  set DB_PASS=tu_contraseña")
        else:
            print("\nNo se pudo conectar a MySQL en %s:%s (%s)." % (
                os.getenv("DB_HOST", "127.0.0.1"), os.getenv("DB_PORT", "3306"), e.args[-1]))
            print("-> Abre el panel de XAMPP y pulsa 'Start' en MySQL, luego vuelve a intentarlo.")
        sys.exit(1)
    c = conn.cursor()

    if reset:
        print("Borrando bases de datos (--reset)...")
        for db in BASES:
            c.execute(f"DROP DATABASE IF EXISTS {db}")

    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    print("1/4 Creando bases y tablas que falten...")
    for s in sentencias(ruta):
        c.execute(s)

    print("2/4 Actualizando tablas existentes (columnas nuevas, emojis/tildes)...")
    for db, tabla, col, ddl in AJUSTES:
        if not existe_tabla(c, db, tabla):
            continue
        try:
            if existe_columna(c, db, tabla, col):
                c.execute(f"ALTER TABLE {db}.{tabla} MODIFY COLUMN {col} {ddl}")
            else:
                c.execute(f"ALTER TABLE {db}.{tabla} ADD COLUMN {col} {ddl}")
        except pymysql.MySQLError as e:
            aviso(f"{db}.{tabla}.{col}: {e.args[-1]}")
    # un evento de RabbitMQ no puede generar dos veces el mismo aviso para el mismo usuario
    c.execute("SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='db_notificaciones' "
              "AND TABLE_NAME='notificaciones' AND INDEX_NAME='uq_evento_usuario'")
    if not c.fetchone():
        try:
            c.execute("ALTER TABLE db_notificaciones.notificaciones ADD UNIQUE KEY uq_evento_usuario (evento_id, usuario_id)")
        except pymysql.MySQLError as e:
            aviso(f"No se pudo crear el índice de eventos: {e.args[-1]}")
    # el correo debe ser único (el registro depende de ello)
    c.execute("SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='db_usuarios' AND TABLE_NAME='usuarios' "
              "AND COLUMN_NAME='email' AND NON_UNIQUE=0")
    if not c.fetchone():
        try:
            c.execute("ALTER TABLE db_usuarios.usuarios ADD UNIQUE (email)")
        except pymysql.MySQLError as e:
            aviso(f"No se pudo hacer único el email (¿hay correos repetidos?): {e.args[-1]}")
    # utf8mb4: sin esto las notificaciones con emoji (🔥🛵) fallan en tablas latin1 de XAMPP
    for db in BASES:
        c.execute(f"ALTER DATABASE {db} CHARACTER SET utf8mb4 COLLATE {COLLATION}")
        c.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_COLLATION<>%s",
                  (db, COLLATION))
        for (t,) in c.fetchall():
            try:
                c.execute(f"ALTER TABLE {db}.{t} CONVERT TO CHARACTER SET utf8mb4 COLLATE {COLLATION}")
            except pymysql.MySQLError as e:
                aviso(f"{db}.{t}: {e.args[-1]}")

    clave_servicios = os.getenv("SERVICE_DB_PASS", "")
    if clave_servicios:
        print("    Creando un usuario de MySQL por servicio, con permisos solo sobre su propia base...")
        clave_sql = pymysql.converters.escape_string(clave_servicios)
        for svc, db in USUARIOS_SERVICIO.items():
            cuenta = f"'svc_{svc}'@'%'"
            c.execute(f"CREATE USER IF NOT EXISTS {cuenta} IDENTIFIED BY '{clave_sql}'")
            c.execute(f"ALTER USER {cuenta} IDENTIFIED BY '{clave_sql}'")
            c.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {db}.* TO {cuenta}")
        c.execute("FLUSH PRIVILEGES")

    print("3/4 Usuarios de demostración...")
    for nombre, email, pw, rol in USUARIOS_DEMO:
        c.execute("SELECT 1 FROM db_usuarios.usuarios WHERE email=%s", (email,))
        if c.fetchone():
            continue
        h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
        c.execute("INSERT INTO db_usuarios.usuarios (nombre,email,password,rol) VALUES (%s,%s,%s,%s)",
                  (nombre, email, h, rol))

    print("4/4 Restaurantes y menú de demostración...")
    c.execute("SELECT COUNT(*) FROM db_restaurantes.restaurantes")
    if c.fetchone()[0] == 0:
        c.execute("SELECT COUNT(*) FROM db_menu.productos")
        hay_productos = c.fetchone()[0] > 0
        for nombre, direccion, tel, productos in RESTAURANTES_DEMO:
            c.execute("INSERT INTO db_restaurantes.restaurantes (nombre,direccion,telefono,activo) VALUES (%s,%s,%s,1)",
                      (nombre, direccion, tel))
            rid = c.lastrowid
            if not hay_productos:
                c.executemany("INSERT INTO db_menu.productos (restaurante_id,nombre,categoria,precio,stock,activo) "
                              "VALUES (%s,%s,%s,%s,%s,1)", [(rid, n, cat, p, s) for n, cat, p, s in productos])
    conn.close()

    print("\nListo. Cuentas de prueba:")
    for nombre, email, pw, rol in USUARIOS_DEMO:
        print(f"   {rol:<11} {email:<22} contraseña: {pw}")


if __name__ == "__main__":
    main()
