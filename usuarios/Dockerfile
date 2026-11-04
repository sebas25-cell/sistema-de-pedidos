# Servicio: usuarios  (contexto de construcción = raíz del proyecto: docker build -f usuarios/Dockerfile .)
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY common ./common
COPY usuarios ./usuarios
RUN useradd -r -u 10001 app && mkdir -p /app/logs && chown app /app/logs
USER app
EXPOSE 8001
CMD ["uvicorn", "usuarios.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
