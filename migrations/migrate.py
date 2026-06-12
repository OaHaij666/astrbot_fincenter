import os
import shutil
import sqlite3
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(_base_dir, 'data', 'fincenter.db')
BACKUP_DIR = os.path.join(_base_dir, 'data', 'backups')


def set_paths(base_dir: str = None):
    global _base_dir, DB_FILE, BACKUP_DIR
    if base_dir:
        _base_dir = base_dir
        DB_FILE = os.path.join(_base_dir, 'data', 'fincenter.db')
        BACKUP_DIR = os.path.join(_base_dir, 'data', 'backups')


def backup_database():
    if not os.path.exists(DB_FILE):
        logger.warning(f"Database file {DB_FILE} does not exist. Skipping backup.")
        return False

    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(BACKUP_DIR, f"fincenter.db.{timestamp}.bak")

    try:
        shutil.copy2(DB_FILE, backup_file)
        logger.info(f"Database backed up to {backup_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to backup database: {e}")
        return False


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [info[1] for info in cursor.fetchall()]
    return column_name in columns


def check_and_add_column(cursor, table, column, col_type):
    if not column_exists(cursor, table, column):
        logger.info(f"Adding column {column} to table {table}...")
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            logger.info(f"Successfully added column {column}.")
        except Exception as e:
            logger.error(f"Failed to add column {column}: {e}")
            raise e
    else:
        logger.debug(f"Column {column} already exists in table {table}.")


def migrate():
    logger.info("Starting database migration...")

    if os.path.exists(DB_FILE):
        if not backup_database():
            logger.error("Backup failed. Aborting migration to prevent data loss.")
            return
    else:
        logger.info("No existing database. Skipping migration (will be created by app).")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        check_and_add_column(cursor, 'user_accounts', 'total_earned', 'FLOAT')
        check_and_add_column(cursor, 'user_accounts', 'total_spent', 'FLOAT')
        check_and_add_column(cursor, 'stock_companies', 'trend_level', 'INTEGER')
        check_and_add_column(cursor, 'stock_companies', 'icon', 'VARCHAR')
        check_and_add_column(cursor, 'goods_market', 'previous_price', 'FLOAT')
        check_and_add_column(cursor, 'stock_news', 'company_code', 'VARCHAR')
        check_and_add_column(cursor, 'stock_news', 'event_type', 'VARCHAR')
        check_and_add_column(cursor, 'stock_news', 'source', 'VARCHAR')
        check_and_add_column(cursor, 'stock_news', 'trend_shift', 'INTEGER')
        check_and_add_column(cursor, 'stock_news', 'immediate_jump', 'FLOAT')
        check_and_add_column(cursor, 'stock_news', 'duration', 'INTEGER')
        check_and_add_column(cursor, 'stock_news', 'remaining_duration', 'INTEGER')
        check_and_add_column(cursor, 'stock_companies', 'description', 'TEXT')
        check_and_add_column(cursor, 'goods_definitions', 'volatility', 'FLOAT')

        conn.commit()
        logger.info("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Migration failed: {e}")
        logger.info("Rolled back changes.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
