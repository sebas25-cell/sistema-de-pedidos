"""Exporta la documentación OpenAPI (Swagger) de cada servicio y la unificada del gateway a docs/openapi/*.json.
Requiere los servicios en ejecución (iniciar.bat).  Uso: python exportar_openapi.py"""
import json, os, sys
import requests
from common import config

SALIDA = os.path.join("docs", "openapi")
os.makedirs(SALIDA, exist_ok=True)
fallas = 0
destinos = {n: config.url(n) for n in config.PUERTOS}
destinos["gateway-unificado"] = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")
for nombre, base in destinos.items():
    try:
        spec = requests.get(f"{base}/openapi.json", timeout=10).json()
        with open(os.path.join(SALIDA, f"{nombre}.json"), "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=2)
        print(f"OK  {nombre}: {sum(len(v) for v in spec['paths'].values())} operaciones")
    except Exception as e:
        fallas += 1
        print(f"ERR {nombre}: {e}")
sys.exit(1 if fallas else 0)
