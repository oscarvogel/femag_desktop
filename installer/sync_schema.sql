-- Tablas de sincronizacion de FEMAG (#804).
-- Ejecutar una sola vez sobre la base de fabrica si el instalador no puede
-- crearlas por permisos del usuario MySQL:
--
--   mysql -u root -p femag_desktop < sync_schema.sql
--
-- Luego volver a instalar/arrancar el agente.

CREATE TABLE IF NOT EXISTS `syncconflict` (
  `id` INTEGER AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  `event_id` VARCHAR(36) NOT NULL,
  `event_type` VARCHAR(255) NOT NULL,
  `aggregate_type` VARCHAR(255) NOT NULL,
  `aggregate_id` VARCHAR(36) NOT NULL,
  `payload` TEXT NOT NULL,
  `reason` TEXT NOT NULL,
  `status` VARCHAR(255) NOT NULL,
  `resolution` TEXT,
  `resolved_at` DATETIME,
  `resolved_by` VARCHAR(255)
);
CREATE UNIQUE INDEX `syncconflict_event_id` ON `syncconflict` (`event_id`);
CREATE INDEX `syncconflict_status_created_at` ON `syncconflict` (`status`, `created_at`);

CREATE TABLE IF NOT EXISTS `synccursor` (
  `id` INTEGER AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  `stream` VARCHAR(32) NOT NULL,
  `cursor_value` INTEGER NOT NULL,
  `last_synced_at` DATETIME,
  `last_error` TEXT
);
CREATE UNIQUE INDEX `synccursor_stream` ON `synccursor` (`stream`);

CREATE TABLE IF NOT EXISTS `syncentitymap` (
  `id` INTEGER AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  `entity_type` VARCHAR(255) NOT NULL,
  `local_id` VARCHAR(64) NOT NULL,
  `global_uid` VARCHAR(36) NOT NULL,
  `local_version` INTEGER NOT NULL,
  `last_published_version` INTEGER
);
CREATE UNIQUE INDEX `syncentitymap_global_uid` ON `syncentitymap` (`global_uid`);
CREATE UNIQUE INDEX `syncentitymap_entity_type_local_id` ON `syncentitymap` (`entity_type`, `local_id`);

CREATE TABLE IF NOT EXISTS `syncinbox` (
  `id` INTEGER AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  `event_id` VARCHAR(36) NOT NULL,
  `event_type` VARCHAR(255) NOT NULL,
  `origin` VARCHAR(255) NOT NULL,
  `aggregate_type` VARCHAR(255) NOT NULL,
  `aggregate_id` VARCHAR(36) NOT NULL,
  `aggregate_version` INTEGER NOT NULL,
  `cursor_value` INTEGER NOT NULL,
  `payload` TEXT NOT NULL,
  `occurred_at` DATETIME,
  `status` VARCHAR(255) NOT NULL,
  `attempts` INTEGER NOT NULL,
  `last_error` TEXT,
  `received_at` DATETIME NOT NULL,
  `applied_at` DATETIME
);
CREATE UNIQUE INDEX `syncinbox_event_id` ON `syncinbox` (`event_id`);
CREATE INDEX `syncinbox_status_cursor_value` ON `syncinbox` (`status`, `cursor_value`);

CREATE TABLE IF NOT EXISTS `syncoutbox` (
  `id` INTEGER AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  `event_id` VARCHAR(36) NOT NULL,
  `event_type` VARCHAR(255) NOT NULL,
  `aggregate_type` VARCHAR(255) NOT NULL,
  `aggregate_id` VARCHAR(36) NOT NULL,
  `aggregate_version` INTEGER NOT NULL,
  `idempotency_key` VARCHAR(200) NOT NULL,
  `payload` TEXT NOT NULL,
  `occurred_at` DATETIME NOT NULL,
  `status` VARCHAR(255) NOT NULL,
  `attempts` INTEGER NOT NULL,
  `next_attempt_at` DATETIME,
  `last_error` TEXT,
  `sent_at` DATETIME
);
CREATE UNIQUE INDEX `syncoutbox_event_id` ON `syncoutbox` (`event_id`);
CREATE UNIQUE INDEX `syncoutbox_idempotency_key` ON `syncoutbox` (`idempotency_key`);
CREATE INDEX `syncoutbox_status_next_attempt_at` ON `syncoutbox` (`status`, `next_attempt_at`);

CREATE TABLE IF NOT EXISTS `syncprojection` (
  `id` INTEGER AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  `resource_type` VARCHAR(255) NOT NULL,
  `resource_uid` VARCHAR(36) NOT NULL,
  `qr_token` VARCHAR(64),
  `order_number` INTEGER,
  `status` VARCHAR(255),
  `version` INTEGER NOT NULL,
  `payload` TEXT NOT NULL,
  `source_updated_at` DATETIME,
  `published_at` DATETIME NOT NULL,
  `cancelled_at` DATETIME
);
CREATE UNIQUE INDEX `syncprojection_qr_token` ON `syncprojection` (`qr_token`);
CREATE UNIQUE INDEX `syncprojection_resource_type_resource_uid` ON `syncprojection` (`resource_type`, `resource_uid`);
