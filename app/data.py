import aiosqlite
import datetime
import math
from typing import Optional, Dict, Any, List

import config

DB_PATH = config.DB_PATH


async def init_moderator_tables():
    """Создаёт таблицы и колонки, необходимые для работы ModeratorBot."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица запросов на верификацию
        await db.execute('''
            CREATE TABLE IF NOT EXISTS pending_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                photo_file_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                admin_notified INTEGER DEFAULT 0
            )
        ''')

        # Новые колонки в meet_tasks (только если таблица уже существует)
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='meet_tasks'"
        ) as cursor:
            meet_tasks_exists = await cursor.fetchone()

        if meet_tasks_exists:
            async with db.execute("PRAGMA table_info(meet_tasks)") as cursor:
                cols = {row[1] for row in await cursor.fetchall()}
            if 'admin_notified' not in cols:
                await db.execute('ALTER TABLE meet_tasks ADD COLUMN admin_notified INTEGER DEFAULT 0')
            if 'video_file_id' not in cols:
                await db.execute('ALTER TABLE meet_tasks ADD COLUMN video_file_id TEXT')

        await db.commit()


# ---------- Верификации ----------

async def get_new_pending_verifications() -> List[Dict]:
    """Верификации со статусом pending, ещё не отправленные администратору."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, photo_file_id, created_at, photo_path "
            "FROM pending_verifications WHERE status = 'pending' AND admin_notified = 0"
        ) as cursor:
            rows = await cursor.fetchall()
    return [{'id': r[0], 'user_id': r[1], 'photo_file_id': r[2], 'created_at': r[3], 'photo_path': r[4]} for r in rows]


async def get_all_pending_verifications() -> List[Dict]:
    """Все верификации со статусом pending."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, photo_file_id, created_at, photo_path "
            "FROM pending_verifications WHERE status = 'pending' ORDER BY created_at"
        ) as cursor:
            rows = await cursor.fetchall()
    return [{'id': r[0], 'user_id': r[1], 'photo_file_id': r[2], 'created_at': r[3], 'photo_path': r[4]} for r in rows]


async def mark_verification_notified(verification_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE pending_verifications SET admin_notified = 1 WHERE id = ?', (verification_id,))
        await db.commit()


async def get_user_id_by_verification(verification_id: int) -> Optional[int]:
    """Возвращает user_id по ID верификации, или None если не найдена."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT user_id FROM pending_verifications WHERE id = ?', (verification_id,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def approve_verification(user_id: int, verification_id: int) -> bool:
    """Атомарно одобряет верификацию. Возвращает False если уже обработана."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pending_verifications SET status = 'approved' WHERE id = ? AND status = 'pending'",
            (verification_id,)
        )
        if db.total_changes == 0:
            return False
        await db.execute('UPDATE profiles SET verified = 1 WHERE user_id = ?', (user_id,))
        # Бейдж verified
        async with db.execute(
            'SELECT 1 FROM user_badges WHERE user_id = ? AND badge_type = ?', (user_id, 'verified')
        ) as cursor:
            exists = await cursor.fetchone()
        if not exists:
            await db.execute('INSERT INTO user_badges (user_id, badge_type) VALUES (?, ?)', (user_id, 'verified'))
        await db.commit()
    return True


async def decline_verification(verification_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE pending_verifications SET status = 'declined' WHERE id = ?", (verification_id,))
        await db.commit()


# ---------- Встречи ----------

async def get_new_meet_tasks_for_admin() -> List[Dict]:
    """Встречи в статусе waiting_admin, ещё не отправленные администратору."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user1_id, user2_id, initiator_id, institute, location, video_file_id, video_path "
            "FROM meet_tasks WHERE status = 'waiting_admin' AND admin_notified = 0"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {'id': r[0], 'user1_id': r[1], 'user2_id': r[2],
         'initiator_id': r[3], 'institute': r[4], 'location': r[5], 'video_file_id': r[6], 'video_path': r[7]}
        for r in rows
    ]


async def get_all_pending_meet_tasks() -> List[Dict]:
    """Все встречи в статусе waiting_admin."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user1_id, user2_id, initiator_id, institute, location, video_file_id, video_path "
            "FROM meet_tasks WHERE status = 'waiting_admin' ORDER BY created_at"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {'id': r[0], 'user1_id': r[1], 'user2_id': r[2],
         'initiator_id': r[3], 'institute': r[4], 'location': r[5], 'video_file_id': r[6], 'video_path': r[7]}
        for r in rows
    ]


async def mark_meet_admin_notified(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE meet_tasks SET admin_notified = 1 WHERE id = ?', (task_id,))
        await db.commit()


async def get_meet_task_by_id(task_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT * FROM meet_tasks WHERE id = ?', (task_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                cols = [d[0] for d in cursor.description]
                return dict(zip(cols, row))
    return None


def _get_seasonal_multiplier() -> tuple:
    """Возвращает (multiplier, name) для сезонных событий."""
    now = datetime.datetime.now()
    if now.month == 2 and now.day == 14:
        return 2.0, "День влюблённых"
    if now.month == 9 and now.day == 1:
        return 1.5, "День знаний"
    return 1.0, ""


async def confirm_meet(task_id: int) -> Optional[Dict]:
    """Атомарно подтверждает встречу: начисляет очки и выдаёт бейджи."""
    multiplier, season_name = _get_seasonal_multiplier()
    points = int(10 * multiplier)
    year_month = datetime.datetime.now().strftime('%Y-%m')

    async with aiosqlite.connect(DB_PATH) as db:
        # Атомарное обновление: только если статус ещё waiting_admin
        await db.execute(
            "UPDATE meet_tasks SET status = 'confirmed', admin_decision = 1 WHERE id = ? AND status = 'waiting_admin'",
            (task_id,)
        )
        if db.total_changes == 0:
            return None  # уже обработано

        async with db.execute('SELECT user1_id, user2_id, video_path FROM meet_tasks WHERE id = ?', (task_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        user1_id, user2_id, video_path = row

        for uid in [user1_id, user2_id]:
            await db.execute(
                '''INSERT INTO user_points (user_id, year_month, points) VALUES (?, ?, ?)
                   ON CONFLICT(user_id, year_month) DO UPDATE SET points = points + ?''',
                (uid, year_month, points, points)
            )
            async with db.execute(
                'SELECT 1 FROM user_badges WHERE user_id = ? AND badge_type = ?', (uid, 'first_meet')
            ) as cursor:
                if not await cursor.fetchone():
                    await db.execute('INSERT INTO user_badges (user_id, badge_type) VALUES (?, ?)', (uid, 'first_meet'))

        await db.commit()

    return {
        'user1_id': user1_id,
        'user2_id': user2_id,
        'points': points,
        'multiplier': multiplier,
        'season_name': season_name,
        'video_path': video_path,
    }


async def decline_meet(task_id: int) -> Optional[Dict]:
    """Атомарно отклоняет встречу."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE meet_tasks SET status = 'declined', admin_decision = 0 WHERE id = ? AND status = 'waiting_admin'",
            (task_id,)
        )
        if db.total_changes == 0:
            return None  # уже обработано

        async with db.execute('SELECT user1_id, user2_id, video_path FROM meet_tasks WHERE id = ?', (task_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None

        await db.commit()

    return {'user1_id': row[0], 'user2_id': row[1], 'video_path': row[2]}


# ---------- Статистика ----------

async def get_stats() -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT COUNT(*) FROM profiles') as cursor:
            total = (await cursor.fetchone())[0]

        async with db.execute('SELECT gender, COUNT(*) FROM profiles GROUP BY gender') as cursor:
            gender_stats = {row[0]: row[1] for row in await cursor.fetchall()}

        async with db.execute("SELECT COUNT(*) FROM meet_tasks WHERE status = 'confirmed'") as cursor:
            meets_confirmed = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM meet_tasks WHERE status = 'waiting_admin'") as cursor:
            meets_pending = (await cursor.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM profiles WHERE verified = 1") as cursor:
            verified_count = (await cursor.fetchone())[0]

        # pending_verifications может не существовать на старых версиях БД
        try:
            async with db.execute("SELECT COUNT(*) FROM pending_verifications WHERE status = 'pending'") as cursor:
                verifications_pending = (await cursor.fetchone())[0]
        except Exception:
            verifications_pending = 0

    return {
        'total': total,
        'male': gender_stats.get('Парень', 0),
        'female': gender_stats.get('Девушка', 0),
        'meets_confirmed': meets_confirmed,
        'meets_pending': meets_pending,
        'verified_count': verified_count,
        'verifications_pending': verifications_pending,
    }


async def get_all_profiles_with_rating() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT user_id, name, gender, rating_sum, rating_weight FROM profiles ORDER BY gender, name'
        ) as cursor:
            rows = await cursor.fetchall()
    result = []
    for user_id, name, gender, r_sum, r_weight in rows:
        rating = round(r_sum / r_weight, 2) if r_weight and r_weight > 0 else 1.0
        rating = max(rating, 1.0)
        result.append({'user_id': user_id, 'name': name, 'gender': gender, 'rating': rating})
    return result


async def get_username(bot, user_id: int) -> str:
    try:
        chat = await bot.get_chat(user_id)
        if chat.username:
            return f"@{chat.username}"
        return f"id{user_id}"
    except Exception:
        return f"id{user_id}"
