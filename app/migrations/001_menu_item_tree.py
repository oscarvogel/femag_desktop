MIGRATION_ID = "001_menu_item_tree"


def migrate(db) -> None:
    existing_columns = {column.name for column in db.get_columns("menuitem")}
    column_sql = {
        "parent_id": "ALTER TABLE menuitem ADD COLUMN parent_id INTEGER NULL",
        "icon": "ALTER TABLE menuitem ADD COLUMN icon VARCHAR(255) NULL",
        "action_key": "ALTER TABLE menuitem ADD COLUMN action_key VARCHAR(255) NULL",
        "route_key": "ALTER TABLE menuitem ADD COLUMN route_key VARCHAR(255) NULL",
        "module": "ALTER TABLE menuitem ADD COLUMN module VARCHAR(255) NULL",
        "is_active": "ALTER TABLE menuitem ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
        "is_placeholder": "ALTER TABLE menuitem ADD COLUMN is_placeholder BOOLEAN NOT NULL DEFAULT 0",
        "requires_permission": "ALTER TABLE menuitem ADD COLUMN requires_permission BOOLEAN NOT NULL DEFAULT 1",
    }
    for column_name, sql in column_sql.items():
        if column_name not in existing_columns:
            db.execute_sql(sql)
