"""Programmatic Alembic entry point used by the application and tests."""
from alembic import command
from alembic.config import Config

from ..config import BACKEND_DIR


def upgrade_database(database_url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # ConfigParser treats percent signs as interpolation syntax.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
