"""Delete expired terminal plans and matching checkpoint threads."""
import argparse
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.errors import PersistenceUnavailable
from app.services.checkpoint_service import get_checkpoint_path
from app.services.persistence_service import PlanStore
from app.services.state_cleanup_service import cleanup_terminal_state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--older-than-days", type=int)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    database_url = settings.database_url.get_secret_value().strip()
    checkpoint_path = get_checkpoint_path()
    if not database_url or checkpoint_path is None:
        raise PersistenceUnavailable()
    days = args.older_than_days or settings.checkpoint_retention_days
    if days < 1 or args.limit < 1 or args.limit > 10000:
        parser.error("retention days and limit must be positive")
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        - timedelta(days=days)
    )
    store = PlanStore(database_url)
    store.initialize()
    try:
        result = cleanup_terminal_state(
            store,
            checkpoint_path,
            cutoff,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    finally:
        store.close()
    print(f"candidates={result.candidates} deleted={result.deleted} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
