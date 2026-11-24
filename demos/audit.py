from sqlalchemy import Connection, inspect, text


def upgrade_audit_table(conn: Connection) -> None:
    """Keep existing local demo databases usable across the audit schema change."""
    columns = inspect(conn).get_columns("hxadmin_audit")
    if all(column["name"] != "action_name" for column in columns):
        conn.execute(text("ALTER TABLE hxadmin_audit ADD COLUMN action_name TEXT"))
