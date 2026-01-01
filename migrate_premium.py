"""
Database migration script to add premium plan fields to User model

Run this script once to add premium plan columns to existing database.
"""

from database import engine, Base
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_premium_fields():
    """Add premium plan fields to users table"""

    with engine.connect() as conn:
        try:
            # Check if columns already exist
            result = conn.execute(text("PRAGMA table_info(users)"))
            existing_columns = [row[1] for row in result]

            logger.info(f"Existing columns: {existing_columns}")

            # Add premium_tier column if it doesn't exist
            if "premium_tier" not in existing_columns:
                logger.info("Adding premium_tier column...")
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN premium_tier VARCHAR(20) DEFAULT 'free'"
                ))
                conn.execute(text("CREATE INDEX ix_users_premium_tier ON users (premium_tier)"))
                logger.info("✓ Added premium_tier column")
            else:
                logger.info("premium_tier column already exists")

            # Add premium_until column if it doesn't exist
            if "premium_until" not in existing_columns:
                logger.info("Adding premium_until column...")
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN premium_until DATETIME NULL"
                ))
                conn.execute(text("CREATE INDEX ix_users_premium_until ON users (premium_until)"))
                logger.info("✓ Added premium_until column")
            else:
                logger.info("premium_until column already exists")

            # Add stripe_customer_id column if it doesn't exist
            if "stripe_customer_id" not in existing_columns:
                logger.info("Adding stripe_customer_id column...")
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(100) NULL"
                ))
                conn.execute(text("CREATE UNIQUE INDEX ix_users_stripe_customer_id ON users (stripe_customer_id)"))
                logger.info("✓ Added stripe_customer_id column")
            else:
                logger.info("stripe_customer_id column already exists")

            # Add stripe_subscription_id column if it doesn't exist
            if "stripe_subscription_id" not in existing_columns:
                logger.info("Adding stripe_subscription_id column...")
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(100) NULL"
                ))
                logger.info("✓ Added stripe_subscription_id column")
            else:
                logger.info("stripe_subscription_id column already exists")

            conn.commit()
            logger.info("✅ Migration completed successfully!")

        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            conn.rollback()
            raise


if __name__ == "__main__":
    logger.info("Starting premium fields migration...")
    migrate_premium_fields()
