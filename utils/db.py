"""SQLite database layer for persisting trade history locally."""

import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

DB_PATH = Path.home() / ".tasty-coach" / "history.db"

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

MIGRATIONS = [
    # Version 1: Initial schema
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        account_number TEXT NOT NULL,
        transaction_type TEXT NOT NULL,
        transaction_sub_type TEXT NOT NULL,
        description TEXT,
        executed_at TEXT NOT NULL,
        transaction_date TEXT NOT NULL,
        value REAL NOT NULL,
        net_value REAL NOT NULL,
        is_estimated_fee INTEGER NOT NULL,
        symbol TEXT,
        instrument_type TEXT,
        underlying_symbol TEXT,
        action TEXT,
        quantity REAL,
        price REAL,
        regulatory_fees REAL,
        clearing_fees REAL,
        commission REAL,
        order_id INTEGER,
        raw_json TEXT,
        synced_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY,
        account_number TEXT NOT NULL,
        time_in_force TEXT,
        order_type TEXT,
        underlying_symbol TEXT,
        underlying_instrument_type TEXT,
        status TEXT NOT NULL,
        size REAL,
        price REAL,
        value REAL,
        received_at TEXT,
        terminal_at TEXT,
        cancelled_at TEXT,
        replacing_order_id INTEGER,
        replaces_order_id INTEGER,
        legs_json TEXT,
        raw_json TEXT,
        synced_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS trade_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_number TEXT NOT NULL,
        underlying_symbol TEXT NOT NULL,
        strategy_type TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        opened_at TEXT,
        closed_at TEXT,
        total_premium_collected REAL DEFAULT 0,
        total_premium_paid REAL DEFAULT 0,
        total_fees REAL DEFAULT 0,
        realized_pl REAL,
        holding_days INTEGER,
        parent_group_id INTEGER,
        notes TEXT,
        FOREIGN KEY (parent_group_id) REFERENCES trade_groups(id)
    );

    CREATE TABLE IF NOT EXISTS trade_group_transactions (
        trade_group_id INTEGER NOT NULL,
        transaction_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        PRIMARY KEY (trade_group_id, transaction_id),
        FOREIGN KEY (trade_group_id) REFERENCES trade_groups(id),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    );

    CREATE TABLE IF NOT EXISTS sync_state (
        account_number TEXT PRIMARY KEY,
        last_transaction_id INTEGER,
        last_order_id INTEGER,
        last_sync_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_txn_underlying ON transactions(underlying_symbol);
    CREATE INDEX IF NOT EXISTS idx_txn_order_id ON transactions(order_id);
    CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(transaction_date);
    CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(transaction_type);
    CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_number);
    CREATE INDEX IF NOT EXISTS idx_orders_underlying ON orders(underlying_symbol);
    CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_number);
    CREATE INDEX IF NOT EXISTS idx_tg_underlying ON trade_groups(underlying_symbol);
    CREATE INDEX IF NOT EXISTS idx_tg_account ON trade_groups(account_number);
    CREATE INDEX IF NOT EXISTS idx_tg_status ON trade_groups(status);
    CREATE INDEX IF NOT EXISTS idx_tg_parent ON trade_groups(parent_group_id);
    CREATE INDEX IF NOT EXISTS idx_tgt_group ON trade_group_transactions(trade_group_id);
    CREATE INDEX IF NOT EXISTS idx_tgt_txn ON trade_group_transactions(transaction_id);

    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );
    INSERT OR IGNORE INTO schema_version (version) VALUES (1);
    """,
    # Version 2: Phase E alert persistence
    """
    CREATE TABLE IF NOT EXISTS alert_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_number TEXT NOT NULL,
        severity TEXT NOT NULL,
        category TEXT NOT NULL,
        message TEXT NOT NULL,
        context TEXT,
        recorded_at TEXT NOT NULL,
        recorded_day TEXT NOT NULL,
        UNIQUE(account_number, category, message, recorded_day)
    );

    CREATE TABLE IF NOT EXISTS alert_views (
        account_number TEXT PRIMARY KEY,
        last_viewed_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_alert_history_account_time
        ON alert_history(account_number, recorded_at DESC);

    INSERT OR IGNORE INTO schema_version (version) VALUES (2);
    """,
]


class TradeDB:
    """SQLite database for trade history persistence."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        """Run schema migrations. Idempotent."""
        cursor = self.conn.cursor()

        # Check current version
        try:
            row = cursor.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            current = row[0] if row and row[0] else 0
        except sqlite3.OperationalError:
            current = 0

        for i, migration in enumerate(MIGRATIONS, start=1):
            if i > current:
                logger.info(f"Running migration v{i}")
                cursor.executescript(migration)

        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- Sync state ---

    def get_sync_state(self, account_number: str) -> dict:
        """Get the last sync watermarks for an account."""
        row = self.conn.execute(
            "SELECT last_transaction_id, last_order_id, last_sync_at "
            "FROM sync_state WHERE account_number = ?",
            (account_number,),
        ).fetchone()
        if row:
            return dict(row)
        return {"last_transaction_id": None, "last_order_id": None, "last_sync_at": None}

    def update_sync_state(
        self,
        account_number: str,
        last_transaction_id: Optional[int] = None,
        last_order_id: Optional[int] = None,
    ) -> None:
        """Update sync watermarks."""
        self.conn.execute(
            """INSERT INTO sync_state (account_number, last_transaction_id, last_order_id, last_sync_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(account_number) DO UPDATE SET
                 last_transaction_id = COALESCE(?, last_transaction_id),
                 last_order_id = COALESCE(?, last_order_id),
                 last_sync_at = datetime('now')""",
            (account_number, last_transaction_id, last_order_id,
             last_transaction_id, last_order_id),
        )
        self.conn.commit()

    # --- Transactions ---

    def upsert_transactions(self, transactions: list[dict]) -> int:
        """Insert transactions, skipping duplicates. Returns count inserted."""
        count = 0
        for txn in transactions:
            try:
                cursor = self.conn.execute(
                    """INSERT OR IGNORE INTO transactions
                       (id, account_number, transaction_type, transaction_sub_type,
                        description, executed_at, transaction_date, value, net_value,
                        is_estimated_fee, symbol, instrument_type, underlying_symbol,
                        action, quantity, price, regulatory_fees, clearing_fees,
                        commission, order_id, raw_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        txn["id"],
                        txn["account_number"],
                        txn["transaction_type"],
                        txn["transaction_sub_type"],
                        txn.get("description"),
                        txn["executed_at"],
                        txn["transaction_date"],
                        txn["value"],
                        txn["net_value"],
                        int(txn["is_estimated_fee"]),
                        txn.get("symbol"),
                        txn.get("instrument_type"),
                        txn.get("underlying_symbol"),
                        txn.get("action"),
                        txn.get("quantity"),
                        txn.get("price"),
                        txn.get("regulatory_fees"),
                        txn.get("clearing_fees"),
                        txn.get("commission"),
                        txn.get("order_id"),
                        json.dumps(txn),
                    ),
                )
                count += cursor.rowcount
            except Exception as e:
                logger.warning(f"Failed to insert transaction {txn.get('id')}: {e}")
        self.conn.commit()
        return count

    def upsert_orders(self, orders: list[dict]) -> int:
        """Insert orders, skipping duplicates. Returns count inserted."""
        count = 0
        for order in orders:
            try:
                cursor = self.conn.execute(
                    """INSERT OR IGNORE INTO orders
                       (id, account_number, time_in_force, order_type,
                        underlying_symbol, underlying_instrument_type, status,
                        size, price, value, received_at, terminal_at, cancelled_at,
                        replacing_order_id, replaces_order_id, legs_json, raw_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        order["id"],
                        order["account_number"],
                        order.get("time_in_force"),
                        order.get("order_type"),
                        order.get("underlying_symbol"),
                        order.get("underlying_instrument_type"),
                        order["status"],
                        order.get("size"),
                        order.get("price"),
                        order.get("value"),
                        order.get("received_at"),
                        order.get("terminal_at"),
                        order.get("cancelled_at"),
                        order.get("replacing_order_id"),
                        order.get("replaces_order_id"),
                        json.dumps(order.get("legs", [])),
                        json.dumps(order),
                    ),
                )
                count += cursor.rowcount
            except Exception as e:
                logger.warning(f"Failed to insert order {order.get('id')}: {e}")
        self.conn.commit()
        return count

    # --- Queries ---

    def get_transactions(
        self,
        account_number: str,
        underlying_symbol: Optional[str] = None,
        transaction_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        """Query stored transactions with optional filters."""
        sql = "SELECT * FROM transactions WHERE account_number = ?"
        params: list[Any] = [account_number]

        if underlying_symbol:
            sql += " AND underlying_symbol = ?"
            params.append(underlying_symbol)
        if transaction_type:
            sql += " AND transaction_type = ?"
            params.append(transaction_type)
        if start_date:
            sql += " AND transaction_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND transaction_date <= ?"
            params.append(end_date)

        sql += " ORDER BY executed_at DESC LIMIT ?"
        params.append(limit)

        return self.conn.execute(sql, params).fetchall()

    def get_ungrouped_transactions(self, account_number: str) -> list[sqlite3.Row]:
        """Get transactions not yet assigned to any trade group, for grouping."""
        return self.conn.execute(
            """SELECT t.* FROM transactions t
               LEFT JOIN trade_group_transactions tgt ON t.id = tgt.transaction_id
               WHERE t.account_number = ? AND tgt.transaction_id IS NULL
                 AND t.transaction_type IN ('Trade', 'Receive Deliver')
               ORDER BY t.executed_at ASC""",
            (account_number,),
        ).fetchall()

    # --- Trade groups ---

    def create_trade_group(
        self,
        account_number: str,
        underlying_symbol: str,
        strategy_type: Optional[str] = None,
        opened_at: Optional[str] = None,
        parent_group_id: Optional[int] = None,
    ) -> int:
        """Create a new trade group. Returns the group ID."""
        cursor = self.conn.execute(
            """INSERT INTO trade_groups
               (account_number, underlying_symbol, strategy_type, status, opened_at, parent_group_id)
               VALUES (?, ?, ?, 'open', ?, ?)""",
            (account_number, underlying_symbol, strategy_type, opened_at, parent_group_id),
        )
        self.conn.commit()
        return cursor.lastrowid

    def link_transaction(self, group_id: int, transaction_id: int, role: str) -> None:
        """Link a transaction to a trade group."""
        self.conn.execute(
            "INSERT OR IGNORE INTO trade_group_transactions VALUES (?, ?, ?)",
            (group_id, transaction_id, role),
        )
        self.conn.commit()

    def update_trade_group(self, group_id: int, **updates) -> None:
        """Update fields on a trade group."""
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [group_id]
        self.conn.execute(
            f"UPDATE trade_groups SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()

    def get_trade_groups(
        self,
        account_number: str,
        underlying_symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        """Query trade groups with optional filters."""
        sql = "SELECT * FROM trade_groups WHERE account_number = ?"
        params: list[Any] = [account_number]

        if underlying_symbol:
            sql += " AND underlying_symbol = ?"
            params.append(underlying_symbol)
        if status:
            sql += " AND status = ?"
            params.append(status)

        sql += " ORDER BY opened_at DESC LIMIT ?"
        params.append(limit)

        return self.conn.execute(sql, params).fetchall()

    def get_group_transactions(self, group_id: int) -> list[sqlite3.Row]:
        """Get all transactions for a trade group."""
        return self.conn.execute(
            """SELECT t.*, tgt.role FROM transactions t
               JOIN trade_group_transactions tgt ON t.id = tgt.transaction_id
               WHERE tgt.trade_group_id = ?
               ORDER BY t.executed_at ASC""",
            (group_id,),
        ).fetchall()

    def get_open_group_for_underlying(
        self, account_number: str, underlying_symbol: str
    ) -> Optional[sqlite3.Row]:
        """Find an open trade group for a given underlying."""
        return self.conn.execute(
            """SELECT * FROM trade_groups
               WHERE account_number = ? AND underlying_symbol = ? AND status = 'open'
               ORDER BY opened_at DESC LIMIT 1""",
            (account_number, underlying_symbol),
        ).fetchone()

    def get_group_net_quantity(self, group_id: int) -> float:
        """Compute net quantity across all transactions in a group.
        Opens are positive, closes are negative."""
        rows = self.conn.execute(
            """SELECT t.action, t.quantity FROM transactions t
               JOIN trade_group_transactions tgt ON t.id = tgt.transaction_id
               WHERE tgt.trade_group_id = ?""",
            (group_id,),
        ).fetchall()

        net = 0.0
        for row in rows:
            qty = float(row["quantity"]) if row["quantity"] else 0.0
            action = row["action"] or ""
            if "Open" in action:
                net += qty
            elif "Close" in action:
                net -= qty
        return net

    def get_roll_chain(self, group_id: int) -> list[sqlite3.Row]:
        """Walk the parent_group_id chain to get all groups in a roll chain."""
        # Walk up to find the root
        root_id = group_id
        seen = {root_id}
        while True:
            row = self.conn.execute(
                "SELECT parent_group_id FROM trade_groups WHERE id = ?", (root_id,)
            ).fetchone()
            if not row or not row["parent_group_id"]:
                break
            root_id = row["parent_group_id"]
            if root_id in seen:
                break
            seen.add(root_id)

        # Walk down from root to collect all children
        chain = []
        queue = [root_id]
        visited = set()
        while queue:
            gid = queue.pop(0)
            if gid in visited:
                continue
            visited.add(gid)
            group = self.conn.execute(
                "SELECT * FROM trade_groups WHERE id = ?", (gid,)
            ).fetchone()
            if group:
                chain.append(group)
                children = self.conn.execute(
                    "SELECT id FROM trade_groups WHERE parent_group_id = ?", (gid,)
                ).fetchall()
                queue.extend(c["id"] for c in children)

        return sorted(chain, key=lambda g: g["opened_at"] or "")
