import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "acwellan.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("=" * 60)
print("ПРОШЕДШИЕ МАТЧИ (последние 10)")
print("=" * 60)

cur.execute("""
    SELECT id, home_team, away_team, status, home_score, away_score, match_date
    FROM matches
    WHERE match_date < datetime('now')
    ORDER BY match_date DESC
    LIMIT 10
""")

rows = cur.fetchall()
if not rows:
    print("Нет прошедших матчей")
else:
    for r in rows:
        print(f"ID: {r[0]} | {r[1]} — {r[2]}")
        print(f"  Статус: {r[3]} | Счёт: {r[4]}:{r[5]} | Дата: {r[6]}")
        print()

print("=" * 60)
print("ПРОГНОЗЫ БЕЗ РЕЗУЛЬТАТА")
print("=" * 60)

cur.execute("""
    SELECT p.id, p.bet_name, p.result, m.home_team, m.away_team, m.status, m.home_score, m.away_score
    FROM predictions p
    JOIN matches m ON p.match_id = m.id
    WHERE p.result IS NULL
    ORDER BY m.match_date DESC
    LIMIT 20
""")

rows = cur.fetchall()
if not rows:
    print("Все прогнозы имеют результат")
else:
    for r in rows:
        print(f"Ставка: {r[1]} | Результат: {r[2]}")
        print(f"  Матч: {r[3]} — {r[4]}")
        print(f"  Статус матча: {r[5]} | Счёт: {r[6]}:{r[7]}")
        print()

conn.close()