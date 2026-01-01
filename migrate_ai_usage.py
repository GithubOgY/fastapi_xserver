"""
Database migration script to add AI usage tracking table

Run this script once to create the ai_usage_tracking table.
"""

from database import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_ai_usage_tracking():
    """Create AI usage tracking table"""

    with engine.connect() as conn:
        try:
            # Check if table already exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_usage_tracking'"))
            table_exists = result.fetchone() is not None

            if table_exists:
                logger.info("ai_usage_tracking table already exists")
                return

            logger.info("Creating ai_usage_tracking table...")

            # Create the table
            conn.execute(text("""
                CREATE TABLE ai_usage_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    usage_date DATE NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """))

            # Create indexes
            conn.execute(text("CREATE INDEX ix_ai_usage_tracking_id ON ai_usage_tracking (id)"))
            conn.execute(text("CREATE INDEX ix_ai_usage_tracking_user_id ON ai_usage_tracking (user_id)"))
            conn.execute(text("CREATE INDEX ix_ai_usage_tracking_usage_date ON ai_usage_tracking (usage_date)"))

            # Create unique constraint
            conn.execute(text("CREATE UNIQUE INDEX _user_date_uc ON ai_usage_tracking (user_id, usage_date)"))

            conn.commit()
            logger.info("✅ AI usage tracking table created successfully!")

        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            conn.rollback()
            raise


if __name__ == "__main__":
    logger.info("Starting AI usage tracking migration...")
    migrate_ai_usage_tracking()
