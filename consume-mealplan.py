#!/usr/bin/env python3
"""Auto-consume stock based on meal plan.

Checks meal_plan for dates up to today, and deducts ingredients from stock
that haven't been consumed yet. Tracks consumed dates in a marker table.

Usage:
  python consume-mealplan.py          # Consume up to today's lunch
  python consume-mealplan.py --dry    # Dry run (show what would be consumed)
"""
import subprocess
import sqlite3
import sys
import os
from datetime import date, datetime

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
GROCY_DB_CONTAINER = "grocy:/config/data/grocy.db"
GROCY_DB_LOCAL = "/tmp/grocy.db"
SEASONINGS_LOCATION_ID = 4  # 調味料 is excluded from consumption


def copy_db_from_container():
    subprocess.run(["docker", "cp", GROCY_DB_CONTAINER, GROCY_DB_LOCAL], check=True)


def copy_db_to_container():
    subprocess.run(["docker", "cp", GROCY_DB_LOCAL, GROCY_DB_CONTAINER], check=True)


def run(dry=False):
    copy_db_from_container()
    conn = sqlite3.connect(GROCY_DB_LOCAL)
    conn.row_factory = sqlite3.Row

    # Create marker table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meal_plan_consumed (
            day TEXT NOT NULL,
            section_id INTEGER NOT NULL,
            recipe_id INTEGER NOT NULL,
            consumed_at TEXT NOT NULL,
            PRIMARY KEY (day, section_id, recipe_id)
        )
    """)
    conn.commit()

    today = date.today().isoformat()
    now_hour = datetime.now().hour

    # Determine which sections to consume:
    # section 1 (昼食) at 12:00 → consume if hour >= 14 (after lunch)
    # section 2 (夕食) at 19:00 → consume if hour >= 23 (after dinner)
    # Past days: consume all sections
    meals = conn.execute("""
        SELECT mp.day, mp.section_id, mp.recipe_id, r.name as recipe_name
        FROM meal_plan mp
        JOIN recipes r ON mp.recipe_id = r.id
        WHERE mp.day <= ?
          AND mp.type = 'recipe'
          AND NOT EXISTS (
              SELECT 1 FROM meal_plan_consumed mpc
              WHERE mpc.day = mp.day
                AND mpc.section_id = mp.section_id
                AND mpc.recipe_id = mp.recipe_id
          )
        ORDER BY mp.day, mp.section_id
    """, (today,)).fetchall()

    consumed = []
    skipped = []

    for meal in meals:
        day = meal["day"]
        section = meal["section_id"]

        # For today, only consume if meal time has passed
        if day == today:
            if section == 1 and now_hour < 14:
                skipped.append(f"  SKIP (昼食まだ): {day} {meal['recipe_name']}")
                continue
            if section == 2 and now_hour < 23:
                skipped.append(f"  SKIP (夕食まだ): {day} {meal['recipe_name']}")
                continue

        # Get ingredients (exclude seasonings)
        ingredients = conn.execute("""
            SELECT rp.product_id, p.name, rp.amount
            FROM recipes_pos rp
            JOIN products p ON rp.product_id = p.id
            WHERE rp.recipe_id = ?
              AND p.location_id != ?
        """, (meal["recipe_id"], SEASONINGS_LOCATION_ID)).fetchall()

        recipe_log = []
        for ing in ingredients:
            # Check current stock
            cur = conn.execute(
                "SELECT amount FROM stock WHERE product_id = ?",
                (ing["product_id"],)
            ).fetchone()

            if not cur or cur["amount"] <= 0:
                recipe_log.append(f"    {ing['name']}: 在庫なし(skip)")
                continue

            new_amount = max(0, cur["amount"] - ing["amount"])

            if not dry:
                if new_amount <= 0:
                    conn.execute("DELETE FROM stock WHERE product_id = ?",
                                 (ing["product_id"],))
                else:
                    conn.execute("UPDATE stock SET amount = ? WHERE product_id = ?",
                                 (new_amount, ing["product_id"]))

                # Log consumption
                conn.execute("""
                    INSERT INTO stock_log
                        (product_id, amount, best_before_date, purchased_date,
                         used_date, spoiled, transaction_type, price,
                         row_created_timestamp, user_id, stock_id)
                    SELECT ?, ?, best_before_date, purchased_date,
                           datetime('now'), 0, 'consume', price,
                           datetime('now'), 1, stock_id
                    FROM stock_log
                    WHERE product_id = ? AND transaction_type = 'purchase' AND undone = 0
                    ORDER BY row_created_timestamp DESC LIMIT 1
                """, (ing["product_id"], -ing["amount"], ing["product_id"]))

            recipe_log.append(f"    {ing['name']}: {cur['amount']} → {new_amount}")

        if not dry:
            conn.execute("""
                INSERT OR IGNORE INTO meal_plan_consumed (day, section_id, recipe_id, consumed_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (day, meal["section_id"], meal["recipe_id"]))

        section_name = "昼食" if section == 1 else "夕食"
        consumed.append(f"  ✓ {day} {section_name}: {meal['recipe_name']}")
        consumed.extend(recipe_log)

    if not dry:
        conn.commit()
        copy_db_to_container()

    # Output
    prefix = "[DRY RUN] " if dry else ""
    if consumed:
        print(f"{prefix}消費処理:")
        print("\n".join(consumed))
    if skipped:
        print(f"\n{prefix}スキップ (時間前):")
        print("\n".join(skipped))
    if not consumed and not skipped:
        print(f"{prefix}消費対象なし")

    conn.close()


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    run(dry=dry)
