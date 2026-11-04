"""Autenticación JWT y control de roles, compartido por todos los servicios.

- Los usuarios reciben un token al iniciar sesión y lo mandan en `Authorization: Bearer <token>`.
- Los servicios se llaman entre sí con la cabecera interna `X-Internal-Key` (rol SISTEMA).
  Cambia JWT_SECRET e INTERNAL_KEY (variables de entorno) si vas a publicar el sistema.
- Swagger muestra el botón "Authorize" gracias al esquema HTTP Bearer declarado aquí.
"""
import hmac
import os
import time
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

SECRET = os.getenv("JWT_SECRET", "monteria-demo-secreto-jwt-cambiar-0123456789")
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "monteria-clave-interna-servicios")
HORAS_SESION = int(os.getenv("JWT_HORAS", "12"))

bearer = HTTPBearer(auto_error=False, bearerFormat="JWT",
                    description="Token JWT que entrega `POST /usuarios/login`. Pégalo sin la palabra 'Bearer'.")


def crear_token(u):
    payload = {
        "sub": str(u["id"]),
        "rol": u["rol"],
        "nombre": u["nombre"],
        "exp": int(time.time()) + HORAS_SESION * 3600,
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def usuario_actual(credenciales: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
                   x_internal_key: Optional[str] = Header(None, include_in_schema=False)):
    if x_internal_key and hmac.compare_digest(x_internal_key.encode(), INTERNAL_KEY.encode()):
        return {"id": 0, "rol": "SISTEMA", "nombre": "sistema"}
    if credenciales is None:
        raise HTTPException(401, "Debes iniciar sesión")
    try:
        data = jwt.decode(credenciales.credentials.strip(), SECRET, algorithms=["HS256"])
        return {"id": int(data["sub"]), "rol": data["rol"], "nombre": data.get("nombre", "")}
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Sesión inválida o vencida, inicia sesión de nuevo")


def requiere(*roles):
    """Dependencia: deja pasar solo a los roles indicados (y siempre a las llamadas internas)."""
    def dep(u=Depends(usuario_actual)):
        if u["rol"] == "SISTEMA" or u["rol"] in roles:
            return u
        raise HTTPException(403, "No tienes permiso para esta acción")
    return dep
