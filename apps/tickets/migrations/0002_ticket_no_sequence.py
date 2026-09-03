from django.db import migrations


class Migration(migrations.Migration):
    """ticket_no needs to be a real auto-incrementing value (the human-facing
    #4821 shown in the UI), separate from the UUID primary key. Django has no
    built-in "auto-increment but not primary key" field, so this sets up a
    plain Postgres sequence and wires it as the column default — the same
    approach as Identity() in the old SQLAlchemy version."""

    dependencies = [("tickets", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE SEQUENCE tickets_ticket_no_seq OWNED BY tickets.ticket_no;"
                "ALTER TABLE tickets ALTER COLUMN ticket_no SET DEFAULT nextval('tickets_ticket_no_seq');"
                "SELECT setval('tickets_ticket_no_seq', 1, false);"
            ),
            reverse_sql=(
                "ALTER TABLE tickets ALTER COLUMN ticket_no DROP DEFAULT;"
                "DROP SEQUENCE IF EXISTS tickets_ticket_no_seq;"
            ),
        ),
    ]
