"""Create the first teacher, plans and a sample note so the app can be tried end to end.
Usage: python seed.py"""
from app.config import settings
from app.db import Database
from app.services.knowledge import KnowledgeBase

db = Database(settings.database_path)
db.execute("INSERT OR IGNORE INTO teachers (id, name, subject, brand_color) VALUES (?, ?, ?, ?)",
           ("subhash", "Subhash Sir", "Rajasthan History", "#2DD4BF"))
# Prices are placeholders (in paise) — set the real ones before launch.
db.execute("INSERT OR IGNORE INTO plans (id, teacher_id, name, amount_paise, duration_days) VALUES "
           "('subhash-monthly', 'subhash', 'Monthly', 0, 30)")
db.execute("INSERT OR IGNORE INTO plans (id, teacher_id, name, amount_paise, duration_days) VALUES "
           "('subhash-yearly', 'subhash', 'Yearly', 0, 365)")
if not db.one("SELECT 1 FROM kb_chunks WHERE teacher_id = 'subhash'"):
    KnowledgeBase(db).add_document("subhash", "Rajasthan History · Chapter 6", (
        "Maharana Pratap (1540–1597) was the ruler of Mewar. He was born on 9 May 1540 at Kumbhalgarh. "
        "He refused to accept the rule of the Mughal emperor Akbar.\n\n"
        "The Battle of Haldighati was fought in 1576 between Maharana Pratap and Akbar's army led by Man Singh. "
        "Maharana Pratap's loyal horse was Chetak. Later he won back most of Mewar and made Chavand his capital. "
        "He died on 19 January 1597."), "chapter-6", "en")
print("Seeded teacher 'subhash'. Set real plan prices in the plans table.")
