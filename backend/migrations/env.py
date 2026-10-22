from alembic import context

from dam.db.tables import metadata

# The connection is supplied by dam.db.engine.migrate via config.attributes.
connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=metadata)
with context.begin_transaction():
    context.run_migrations()
