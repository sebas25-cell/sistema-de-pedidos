import os

import pymysql


def get_conn(db_name):
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=db_name,
        charset="utf8mb4",          # necesario para emojis y tildes en las notificaciones
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def query(db, sql, params=(), one=False):
    conn = get_conn(db)
    try:
        with conn.cursor() as c:
            c.execute(sql, params)
            return c.fetchone() if one else c.fetchall()
    finally:
        conn.close()


def execute(db, sql, params=()):
    """Ejecuta INSERT/UPDATE/DELETE. Devuelve (lastrowid, filas_afectadas)."""
    conn = get_conn(db)
    try:
        with conn.cursor() as c:
            c.execute(sql, params)
            conn.commit()
            return c.lastrowid, c.rowcount
    finally:
        conn.close()
