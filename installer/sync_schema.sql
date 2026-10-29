-- Tablas de sincronizacion de FEMAG (#804).
-- Se puede ejecutar varias veces: crea tablas e indices solo si faltan.
--
--   mysql -u root -p NOMBRE_BASE < sync_schema.sql
--
-- No usar contra la base equivocada: el nombre de la base es el DB_NAME de
-- C:\ProgramData\FEMAG\webapp.env.

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

CREATE TABLE IF NOT EXISTS `synccursor` (
  `id` INTEGER AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  `stream` VARCHAR(32) NOT NULL,
  `cursor_value` INTEGER NOT NULL,
  `last_synced_at` DATETIME,
  `last_error` TEXT
);

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

DROP PROCEDURE IF EXISTS `femag_sync_add_index`;

DELIMITER //
CREATE PROCEDURE `femag_sync_add_index`(
  IN p_table VARCHAR(64),
  IN p_index VARCHAR(64),
  IN p_ddl TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = p_table
      AND index_name = p_index
  ) THEN
    SET @femag_sql = p_ddl;
    PREPARE femag_stmt FROM @femag_sql;
    EXECUTE femag_stmt;
    DEALLOCATE PREPARE femag_stmt;
  END IF;
END//
DELIMITER ;

CALL `femag_sync_add_index`('syncconflict', 'syncconflict_event_id', 'CREATE UNIQUE INDEX `syncconflict_event_id` ON `syncconflict` (`event_id`)');
CALL `femag_sync_add_index`('syncconflict', 'syncconflict_status_created_at', 'CREATE INDEX `syncconflict_status_created_at` ON `syncconflict` (`status`, `created_at`)');
CALL `femag_sync_add_index`('synccursor', 'synccursor_stream', 'CREATE UNIQUE INDEX `synccursor_stream` ON `synccursor` (`stream`)');
CALL `femag_sync_add_index`('syncentitymap', 'syncentitymap_global_uid', 'CREATE UNIQUE INDEX `syncentitymap_global_uid` ON `syncentitymap` (`global_uid`)');
CALL `femag_sync_add_index`('syncentitymap', 'syncentitymap_entity_type_local_id', 'CREATE UNIQUE INDEX `syncentitymap_entity_type_local_id` ON `syncentitymap` (`entity_type`, `local_id`)');
CALL `femag_sync_add_index`('syncinbox', 'syncinbox_event_id', 'CREATE UNIQUE INDEX `syncinbox_event_id` ON `syncinbox` (`event_id`)');
CALL `femag_sync_add_index`('syncinbox', 'syncinbox_status_cursor_value', 'CREATE INDEX `syncinbox_status_cursor_value` ON `syncinbox` (`status`, `cursor_value`)');
CALL `femag_sync_add_index`('syncoutbox', 'syncoutbox_event_id', 'CREATE UNIQUE INDEX `syncoutbox_event_id` ON `syncoutbox` (`event_id`)');
CALL `femag_sync_add_index`('syncoutbox', 'syncoutbox_idempotency_key', 'CREATE UNIQUE INDEX `syncoutbox_idempotency_key` ON `syncoutbox` (`idempotency_key`)');
CALL `femag_sync_add_index`('syncoutbox', 'syncoutbox_status_next_attempt_at', 'CREATE INDEX `syncoutbox_status_next_attempt_at` ON `syncoutbox` (`status`, `next_attempt_at`)');
CALL `femag_sync_add_index`('syncprojection', 'syncprojection_qr_token', 'CREATE UNIQUE INDEX `syncprojection_qr_token` ON `syncprojection` (`qr_token`)');
CALL `femag_sync_add_index`('syncprojection', 'syncprojection_resource_type_resource_uid', 'CREATE UNIQUE INDEX `syncprojection_resource_type_resource_uid` ON `syncprojection` (`resource_type`, `resource_uid`)');

DROP PROCEDURE `femag_sync_add_index`;
