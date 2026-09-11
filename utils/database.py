# Component Manifest Contract Header
__module_name__ = "three_concern_persistence_manager"
__build_version__ = "1.5.1-stable"
__spec_contract_hash__ = "0x105_three_concern_v2"

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

class ThreeConcernDatabaseManager:
    """Manages transactional isolation across decoupled price, metadata, and audit dataspaces."""

    def __init__(self, base_dir: str = "market_data"):
        self.price_db_path = os.path.join(base_dir, "warehouse", "price_warehouse.db")
        self.meta_db_path = os.path.join(base_dir, "metadata", "metadata.db")
        self.audit_db_path = os.path.join(base_dir, "audit", "audit.db")

        os.makedirs(os.path.dirname(self.price_db_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.meta_db_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.audit_db_path), exist_ok=True)

        self.initialize_all_schemas()

    @contextmanager
    def _connection(self, db_path: str) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    @contextmanager
    def price_db(self) -> Generator[sqlite3.Connection, None, None]:
        with self._connection(self.price_db_path) as conn:
            yield conn

    @contextmanager
    def metadata_db(self) -> Generator[sqlite3.Connection, None, None]:
        with self._connection(self.meta_db_path) as conn:
            yield conn

    @contextmanager
    def audit_db(self) -> Generator[sqlite3.Connection, None, None]:
        with self._connection(self.audit_db_path) as conn:
            yield conn

    def initialize_all_schemas(self):
        """Constructs schema layout partitions containing unique timeframe identifiers."""
        with self.price_db() as conn:
            for schema in ["crypto", "forex", "metal", "index"]:
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {schema}_candles (
                        timestamp INTEGER NOT NULL,
                        symbol TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        volume REAL NOT NULL,
                        quote_volume REAL DEFAULT 0.0,
                        trade_count INTEGER DEFAULT 0,
                        job_id TEXT NOT NULL,
                        PRIMARY KEY (symbol, timeframe, timestamp)
                    );
                """)
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{schema}_time ON {schema}_candles (symbol, timeframe, timestamp);")

        with self.metadata_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS asset_registry (
                    symbol TEXT PRIMARY KEY, asset_class TEXT NOT NULL, venue TEXT NOT NULL, provider TEXT NOT NULL,
                    tick_size REAL NOT NULL, price_precision INTEGER NOT NULL, volume_precision INTEGER NOT NULL,
                    base_currency TEXT NOT NULL, quote_currency TEXT NOT NULL, trading_hours TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_scheduler (
                    job_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
                    chunk_year INTEGER NOT NULL, chunk_month INTEGER NOT NULL, status TEXT NOT NULL,
                    retries INTEGER DEFAULT 0, started_at INTEGER, finished_at INTEGER, error_msg TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dataset_manifests (
                    dataset_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, venue TEXT NOT NULL,
                    provider TEXT NOT NULL, start_timestamp INTEGER NOT NULL, end_timestamp INTEGER NOT NULL,
                    total_rows INTEGER NOT NULL, parser_version TEXT NOT NULL, warehouse_version TEXT NOT NULL,
                    file_hash_sha256 TEXT NOT NULL, download_url TEXT NOT NULL, created_at INTEGER NOT NULL
                );
            """)

        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

db_manager = ThreeConcernDatabaseManager()
# Component Manifest Contract Header
__module_name__ = "three_concern_persistence_manager"
__build_version__ = "1.5.1-stable"
__spec_contract_hash__ = "0x105_three_concern_v2"

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator


class ThreeConcernDatabaseManager:
    """Manages transactional isolation across decoupled price, metadata, and audit dataspaces."""

    def __init__(self, base_dir: str = "market_data"):
        self.price_db_path = os.path.join(base_dir, "warehouse", "price_warehouse.db")
        self.meta_db_path = os.path.join(base_dir, "metadata", "metadata.db")
        self.audit_db_path = os.path.join(base_dir, "audit", "audit.db")

        os.makedirs(os.path.dirname(self.price_db_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.meta_db_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.audit_db_path), exist_ok=True)

        self.initialize_all_schemas()

    @contextmanager
    def _connection(self, db_path: str) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    @contextmanager
    def price_db(self) -> Generator[sqlite3.Connection, None, None]:
        with self._connection(self.price_db_path) as conn:
            yield conn

    @contextmanager
    def metadata_db(self) -> Generator[sqlite3.Connection, None, None]:
        with self._connection(self.meta_db_path) as conn:
            yield conn

    @contextmanager
    def audit_db(self) -> Generator[sqlite3.Connection, None, None]:
        with self._connection(self.audit_db_path) as conn:
            yield conn

    def initialize_all_schemas(self):
        """Constructs schema layout partitions containing unique timeframe identifiers."""
        with self.price_db() as conn:
            for schema in ["crypto", "forex", "metal", "index"]:
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {schema}_candles (
                        timestamp INTEGER NOT NULL,
                        symbol TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        volume REAL NOT NULL,
                        quote_volume REAL DEFAULT 0.0,
                        trade_count INTEGER DEFAULT 0,
                        job_id TEXT NOT NULL,
                        PRIMARY KEY (symbol, timeframe, timestamp)
                    );
                """)
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{schema}_time ON {schema}_candles (symbol, timeframe, timestamp);")

        with self.metadata_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS asset_registry (
                    symbol TEXT PRIMARY KEY, asset_class TEXT NOT NULL, venue TEXT NOT NULL, provider TEXT NOT NULL,
                    tick_size REAL NOT NULL, price_precision INTEGER NOT NULL, volume_precision INTEGER NOT NULL,
                    base_currency TEXT NOT NULL, quote_currency TEXT NOT NULL, trading_hours TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_scheduler (
                    job_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
                    chunk_year INTEGER NOT NULL, chunk_month INTEGER NOT NULL, status TEXT NOT NULL,
                    retries INTEGER DEFAULT 0, started_at INTEGER, finished_at INTEGER, error_msg TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dataset_manifests (
                    dataset_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, venue TEXT NOT NULL,
                    provider TEXT NOT NULL, start_timestamp INTEGER NOT NULL, end_timestamp INTEGER NOT NULL,
                    total_rows INTEGER NOT NULL, parser_version TEXT NOT NULL, warehouse_version TEXT NOT NULL,
                    file_hash_sha256 TEXT NOT NULL, download_url TEXT NOT NULL, created_at INTEGER NOT NULL
                );
            """)

        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
        with self.audit_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_gap_logs (
                    gap_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, gap_start_timestamp INTEGER NOT NULL, gap_end_timestamp INTEGER NOT NULL,
                    missing_candles_count INTEGER NOT NULL, severity_level TEXT NOT NULL, detected_at INTEGER NOT NULL
                );
            """)

        # Create the market_data table for historical data ingestion
        with self.price_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    spread REAL NOT NULL,
                    provider TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    ingestion_time INTEGER NOT NULL,
                    quality_score REAL NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_data_time ON market_data (symbol, timeframe, timestamp);")

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file

    @property
    def connection(self):
        """Returns the raw database connection for direct access."""
        return self.price_db

    @property
    def db_manager(self):
        """Returns the instantiated ThreeConcernDatabaseManager instance for module-wide access."""
        return self

db_manager = ThreeConcernDatabaseManager()

# Export public API for backward compatibility
# This ensures old imports like `from utils.database import db` work
# while using the correct underlying instance

db = db_manager

# End of file
