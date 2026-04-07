"""
SQLite database for SwipeDeals.
Stores all scraped deals with timestamps for expiry tracking.
"""

import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deals.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS deals (
            asin        TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            category    TEXT NOT NULL,
            price       REAL NOT NULL,
            was_price   REAL NOT NULL,
            discount    INTEGER NOT NULL,
            img_url     TEXT,
            product_url TEXT,
            store       TEXT DEFAULT 'Amazon',
            scraped_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            active      INTEGER DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_category ON deals(category);
        CREATE INDEX IF NOT EXISTS idx_active ON deals(active);
        CREATE INDEX IF NOT EXISTS idx_discount ON deals(discount);
    """)
    conn.commit()
    conn.close()


def upsert_deal(deal):
    """Insert or update a deal. Reactivates if already exists."""
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()

    conn.execute("""
        INSERT INTO deals (asin, title, category, price, was_price, discount, img_url, product_url, store, scraped_at, expires_at, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(asin) DO UPDATE SET
            price = excluded.price,
            was_price = excluded.was_price,
            discount = excluded.discount,
            img_url = excluded.img_url,
            scraped_at = excluded.scraped_at,
            expires_at = excluded.expires_at,
            active = 1
    """, (
        deal["asin"], deal["title"], deal["category"],
        deal["price"], deal["was"], deal["discount"],
        deal["img"], deal["url"], deal.get("store", "Amazon"),
        now, expires
    ))
    conn.commit()
    conn.close()


def expire_old_deals():
    """Mark deals older than 24h as inactive."""
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    cursor = conn.execute(
        "UPDATE deals SET active = 0 WHERE expires_at < ? AND active = 1", (now,)
    )
    expired = cursor.rowcount
    conn.commit()
    conn.close()
    return expired


def delete_expired():
    """Permanently remove deals expired for more than 7 days."""
    conn = get_conn()
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    cursor = conn.execute("DELETE FROM deals WHERE expires_at < ? AND active = 0", (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_active_deals(category=None, min_discount=50):
    """Get active deals filtered by category and minimum discount."""
    conn = get_conn()
    query = "SELECT * FROM deals WHERE active = 1 AND discount >= ?"
    params = [min_discount]

    if category:
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY discount DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    """Get database stats."""
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM deals WHERE active = 1").fetchone()[0]
    by_cat = conn.execute(
        "SELECT category, COUNT(*) as cnt, AVG(discount) as avg_disc "
        "FROM deals WHERE active = 1 GROUP BY category"
    ).fetchall()
    conn.close()
    return {"total": total, "active": active, "by_category": [dict(r) for r in by_cat]}


# Auto-init on import
init_db()
