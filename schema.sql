-- Sistema de pedidos - Montería
-- Estructura de las 7 bases de datos (una por microservicio).
-- Se puede importar desde phpMyAdmin o dejar que `python setup_db.py` lo ejecute (recomendado: además
-- migra tablas ya existentes y crea los datos de demostración).
-- Es seguro ejecutarlo varias veces: todo usa IF NOT EXISTS.

CREATE DATABASE IF NOT EXISTS db_usuarios       CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_restaurantes   CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_menu           CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_pedidos        CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_pagos          CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_domicilios     CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS db_notificaciones CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- usuarios
CREATE TABLE IF NOT EXISTS db_usuarios.usuarios (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  nombre     VARCHAR(100) NOT NULL,
  email      VARCHAR(150) NOT NULL UNIQUE,
  password   VARCHAR(100) NOT NULL,                      -- hash bcrypt
  rol        VARCHAR(20)  NOT NULL DEFAULT 'CLIENTE',    -- CLIENTE | ADMIN | REPARTIDOR
  disponible TINYINT(1) NOT NULL DEFAULT 0,               -- estado de disponibilidad del repartidor
  created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- restaurantes
CREATE TABLE IF NOT EXISTS db_restaurantes.restaurantes (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  nombre    VARCHAR(100) NOT NULL,
  direccion VARCHAR(200) NOT NULL DEFAULT '',
  telefono  VARCHAR(30)  NULL,
  activo    TINYINT(1)   NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- menú
CREATE TABLE IF NOT EXISTS db_menu.productos (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  restaurante_id INT           NOT NULL,
  nombre         VARCHAR(100)  NOT NULL,
  categoria      VARCHAR(50)   NULL,
  precio         DECIMAL(10,2) NOT NULL,
  stock          INT           NOT NULL DEFAULT 0,
  activo         TINYINT(1)    NOT NULL DEFAULT 1,
  INDEX idx_restaurante (restaurante_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- pedidos
CREATE TABLE IF NOT EXISTS db_pedidos.pedidos (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  cliente_id     INT           NOT NULL,
  restaurante_id INT           NOT NULL,
  total          DECIMAL(12,2) NOT NULL,
  direccion      VARCHAR(255)  NOT NULL,
  estado         VARCHAR(20)   NOT NULL DEFAULT 'CREADO',  -- CREADO>CONFIRMADO>EN_COCINA>LISTO>EN_CAMINO>ENTREGADO | CANCELADO
  created_at     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_cliente (cliente_id),
  INDEX idx_estado (estado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS db_pedidos.detalle_pedido (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  pedido_id   INT           NOT NULL,
  producto_id INT           NOT NULL,
  nombre      VARCHAR(100)  NULL,                          -- nombre del producto al momento de la compra
  cantidad    INT           NOT NULL,
  precio      DECIMAL(10,2) NOT NULL,                      -- precio unitario al momento de la compra
  INDEX idx_pedido (pedido_id),
  FOREIGN KEY (pedido_id) REFERENCES db_pedidos.pedidos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- pagos
CREATE TABLE IF NOT EXISTS db_pagos.pagos (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  pedido_id  INT           NOT NULL,
  monto      DECIMAL(12,2) NOT NULL,
  metodo     VARCHAR(20)   NOT NULL,                       -- EFECTIVO | TARJETA | NEQUI
  estado     VARCHAR(20)   NOT NULL DEFAULT 'PENDIENTE',   -- PENDIENTE | PAGADO | FALLIDO | REEMBOLSADO
  created_at TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_pedido (pedido_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- domicilios
CREATE TABLE IF NOT EXISTS db_domicilios.domicilios (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  pedido_id     INT         NOT NULL,
  repartidor_id INT         NULL,                          -- NULL = aún sin repartidor
  estado        VARCHAR(20) NOT NULL DEFAULT 'ASIGNADO',   -- ASIGNADO | EN_RUTA | ENTREGADO
  created_at    TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_pedido (pedido_id),
  INDEX idx_repartidor (repartidor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------- notificaciones
CREATE TABLE IF NOT EXISTS db_notificaciones.notificaciones (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  usuario_id INT          NOT NULL,
  mensaje    VARCHAR(255) NOT NULL,
  leido      TINYINT(1)   NOT NULL DEFAULT 0,
  evento_id  VARCHAR(40)  NULL,                          -- id del evento de RabbitMQ que la originó
  created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_usuario (usuario_id),
  UNIQUE KEY uq_evento_usuario (evento_id, usuario_id)    -- consumo idempotente: un evento repetido no duplica avisos
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
