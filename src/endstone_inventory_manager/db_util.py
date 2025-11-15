"""
Database utility for storing player inventory and ender chest data.
Based on PrimeBDS's database implementation.
"""

import sqlite3
import threading
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from endstone import Player


# Database folder path
DB_FOLDER = Path("plugins/inventory_manager_data")
DB_FOLDER.mkdir(parents=True, exist_ok=True)


@dataclass
class User:
    """User data structure"""
    xuid: str
    name: str
    last_join: int = 0
    last_leave: int = 0


@dataclass
class InventoryItem:
    """Inventory item data structure"""
    xuid: str
    name: str
    slot_type: str  # "slot", "helmet", "chestplate", "leggings", "boots", "offhand"
    slot: int
    item_type: str
    amount: int
    damage: int
    display_name: str
    enchants: str  # JSON string
    lore: str      # JSON string
    unbreakable: bool
    data: Optional[int]


class DatabaseManager:
    """Base database manager with thread-safe operations"""

    _lock = threading.Lock()

    def __init__(self, db_name: str):
        """Initialize database connection"""
        self.db_path = DB_FOLDER / (db_name if db_name.endswith('.db') else db_name + '.db')
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        # Enable WAL mode for better concurrency
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.cursor = self.conn.cursor()

    def execute(self, query: str, params: tuple = (), readonly: bool = False) -> sqlite3.Cursor:
        """Execute a database query with thread safety"""
        if readonly:
            # For read-only queries, use a separate connection
            read_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            cursor = read_conn.cursor()
            cursor.execute(query, params)
            return cursor
        else:
            # For write queries, use lock
            with self._lock:
                self.cursor.execute(query, params)
                if not query.strip().upper().startswith("SELECT"):
                    self.conn.commit()
                return self.cursor

    def close(self):
        """Close database connection"""
        self.conn.close()


class InventoryDB(DatabaseManager):
    """Database for storing player inventory and ender chest data"""

    def __init__(self, db_name: str = "inventories.db"):
        """Initialize inventory database"""
        super().__init__(db_name)
        self.create_tables()

    def create_tables(self):
        """Create database tables if they don't exist"""
        # Users table
        self.execute("""
            CREATE TABLE IF NOT EXISTS users (
                xuid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                last_join INTEGER DEFAULT 0,
                last_leave INTEGER DEFAULT 0
            )
        """)

        # Inventories table
        self.execute("""
            CREATE TABLE IF NOT EXISTS inventories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                xuid TEXT NOT NULL,
                name TEXT NOT NULL,
                slot_type TEXT NOT NULL,
                slot INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                damage INTEGER DEFAULT 0,
                display_name TEXT,
                enchants TEXT,
                lore TEXT,
                unbreakable INTEGER DEFAULT 0,
                data INTEGER
            )
        """)

        # Ender chests table
        self.execute("""
            CREATE TABLE IF NOT EXISTS ender_chests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                xuid TEXT NOT NULL,
                name TEXT NOT NULL,
                slot INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                damage INTEGER DEFAULT 0,
                display_name TEXT,
                enchants TEXT,
                lore TEXT,
                unbreakable INTEGER DEFAULT 0,
                data INTEGER
            )
        """)

        # Create indices for faster lookups
        self.execute("CREATE INDEX IF NOT EXISTS idx_inventories_xuid ON inventories(xuid)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_ender_chests_xuid ON ender_chests(xuid)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_users_name ON users(name)")

    def save_user(self, player: Player, join_time: int):
        """Save or update user information"""
        with self._lock:
            self.cursor.execute("""
                INSERT OR REPLACE INTO users (xuid, name, last_join)
                VALUES (?, ?, ?)
            """, (player.xuid, player.name, join_time))
            self.conn.commit()

    def update_user_leave_time(self, xuid: str, leave_time: int):
        """Update user's last leave time"""
        with self._lock:
            self.cursor.execute("""
                UPDATE users SET last_leave = ? WHERE xuid = ?
            """, (leave_time, xuid))
            self.conn.commit()

    def get_user_by_name(self, name: str) -> Optional[User]:
        """Get user by name (case-insensitive partial match)"""
        self.cursor.execute("""
            SELECT xuid, name, last_join, last_leave
            FROM users
            WHERE LOWER(name) LIKE LOWER(?)
            ORDER BY last_join DESC
            LIMIT 1
        """, (f"%{name}%",))

        row = self.cursor.fetchone()
        if row:
            return User(xuid=row[0], name=row[1], last_join=row[2], last_leave=row[3])
        return None

    def search_users_by_name(self, name: str) -> List[User]:
        """Search for users by name (case-insensitive partial match)"""
        self.cursor.execute("""
            SELECT xuid, name, last_join, last_leave
            FROM users
            WHERE LOWER(name) LIKE LOWER(?)
            ORDER BY last_join DESC
        """, (f"%{name}%",))

        users = []
        for row in self.cursor.fetchall():
            users.append(User(xuid=row[0], name=row[1], last_join=row[2], last_leave=row[3]))
        return users

    def save_inventory(self, player: Player):
        """Save player's inventory to database"""
        # Prepare inventory data
        values = []

        # Main inventory slots
        for i in range(player.inventory.size):
            item = player.inventory.get_item(i)
            if not item or str(item.type) == "minecraft:air":
                continue

            # Extract item metadata
            meta = getattr(item, "item_meta", None)
            display_name = ""
            enchants = {}
            lore = []
            unbreakable = False

            if meta:
                display_name = getattr(meta, "display_name", "")
                enchants = getattr(meta, "enchants", {})
                lore = getattr(meta, "lore", [])
                unbreakable = getattr(meta, "is_unbreakable", False)

            values.append((
                player.xuid,
                player.name,
                "slot",
                i,
                str(item.type),
                item.amount,
                getattr(meta, "damage", 0) if meta else 0,
                display_name,
                json.dumps(enchants),
                json.dumps(lore),
                1 if unbreakable else 0,
                getattr(item, "data", None)
            ))

        # Armor slots
        armor_items = [
            ("helmet", getattr(player.inventory, "helmet", None)),
            ("chestplate", getattr(player.inventory, "chestplate", None)),
            ("leggings", getattr(player.inventory, "leggings", None)),
            ("boots", getattr(player.inventory, "boots", None)),
            ("offhand", getattr(player.inventory, "item_in_off_hand", None))
        ]

        for slot_type, item in armor_items:
            if not item or str(item.type) == "minecraft:air":
                continue

            meta = getattr(item, "item_meta", None)
            display_name = ""
            enchants = {}
            lore = []
            unbreakable = False

            if meta:
                display_name = getattr(meta, "display_name", "")
                enchants = getattr(meta, "enchants", {})
                lore = getattr(meta, "lore", [])
                unbreakable = getattr(meta, "is_unbreakable", False)

            values.append((
                player.xuid,
                player.name,
                slot_type,
                0,  # Armor slots don't have slot numbers
                str(item.type),
                item.amount,
                getattr(meta, "damage", 0) if meta else 0,
                display_name,
                json.dumps(enchants),
                json.dumps(lore),
                1 if unbreakable else 0,
                getattr(item, "data", None)
            ))

        # Save to database
        with self._lock:
            # Delete old inventory data
            self.cursor.execute("DELETE FROM inventories WHERE xuid = ?", (player.xuid,))

            # Insert new inventory data
            if values:
                self.cursor.executemany("""
                    INSERT INTO inventories
                    (xuid, name, slot_type, slot, type, amount, damage, display_name, enchants, lore, unbreakable, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values)

            self.conn.commit()

    def get_inventory(self, xuid: str) -> List[Dict[str, Any]]:
        """Get player's inventory from database"""
        self.cursor.execute("""
            SELECT xuid, name, slot_type, slot, type, amount, damage, display_name, enchants, lore, unbreakable, data
            FROM inventories
            WHERE xuid = ?
        """, (xuid,))

        items = []
        for row in self.cursor.fetchall():
            try:
                # Parse JSON fields
                enchants = {}
                lore = []

                if row[8] and row[8] not in ("null", "0", ""):
                    try:
                        enchants = json.loads(row[8])
                    except:
                        enchants = {}

                if row[9] and row[9] not in ("null", "0", ""):
                    try:
                        lore = json.loads(row[9])
                    except:
                        lore = []

                items.append({
                    "xuid": row[0],
                    "name": row[1],
                    "slot_type": row[2],
                    "slot": int(row[3]) if row[3] is not None else 0,
                    "type": row[4] or "minecraft:air",
                    "amount": int(row[5]) if row[5] is not None else 1,
                    "damage": int(row[6]) if row[6] is not None else 0,
                    "display_name": row[7] or "",
                    "enchants": enchants,
                    "lore": lore,
                    "unbreakable": bool(row[10]) if row[10] is not None else False,
                    "data": int(row[11]) if row[11] is not None else None
                })
            except Exception as e:
                print(f"[InventoryDB] Failed to load inventory row for {xuid}: {e}")
                continue

        return items

    def save_enderchest(self, player: Player):
        """Save player's ender chest to database"""
        values = []

        # Ender chest slots
        for i in range(player.ender_chest.size):
            item = player.ender_chest.get_item(i)
            if not item or str(item.type) == "minecraft:air":
                continue

            # Extract item metadata
            meta = getattr(item, "item_meta", None)
            display_name = ""
            enchants = {}
            lore = []
            unbreakable = False

            if meta:
                display_name = getattr(meta, "display_name", "")
                enchants = getattr(meta, "enchants", {})
                lore = getattr(meta, "lore", [])
                unbreakable = getattr(meta, "is_unbreakable", False)

            values.append((
                player.xuid,
                player.name,
                i,
                str(item.type),
                item.amount,
                getattr(meta, "damage", 0) if meta else 0,
                display_name,
                json.dumps(enchants),
                json.dumps(lore),
                1 if unbreakable else 0,
                getattr(item, "data", None)
            ))

        # Save to database
        with self._lock:
            # Delete old ender chest data
            self.cursor.execute("DELETE FROM ender_chests WHERE xuid = ?", (player.xuid,))

            # Insert new ender chest data
            if values:
                self.cursor.executemany("""
                    INSERT INTO ender_chests
                    (xuid, name, slot, type, amount, damage, display_name, enchants, lore, unbreakable, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values)

            self.conn.commit()

    def get_enderchest(self, xuid: str) -> List[Dict[str, Any]]:
        """Get player's ender chest from database"""
        self.cursor.execute("""
            SELECT xuid, name, slot, type, amount, damage, display_name, enchants, lore, unbreakable, data
            FROM ender_chests
            WHERE xuid = ?
        """, (xuid,))

        items = []
        for row in self.cursor.fetchall():
            try:
                # Parse JSON fields
                enchants = {}
                lore = []

                if row[7] and row[7] not in ("null", "0", ""):
                    try:
                        enchants = json.loads(row[7])
                    except:
                        enchants = {}

                if row[8] and row[8] not in ("null", "0", ""):
                    try:
                        lore = json.loads(row[8])
                    except:
                        lore = []

                items.append({
                    "xuid": row[0],
                    "name": row[1],
                    "slot": int(row[2]) if row[2] is not None else 0,
                    "type": row[3] or "minecraft:air",
                    "amount": int(row[4]) if row[4] is not None else 1,
                    "damage": int(row[5]) if row[5] is not None else 0,
                    "display_name": row[6] or "",
                    "enchants": enchants,
                    "lore": lore,
                    "unbreakable": bool(row[9]) if row[9] is not None else False,
                    "data": int(row[10]) if row[10] is not None else None
                })
            except Exception as e:
                print(f"[InventoryDB] Failed to load ender chest row for {xuid}: {e}")
                continue

        return items

