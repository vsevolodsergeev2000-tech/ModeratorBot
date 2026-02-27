import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

import config
from data import (
    init_moderator_tables,
    get_new_pending_verifications, mark_verification_notified,
    get_new_meet_tasks_for_admin, mark_meet_admin_notified,
)
from handlers import router
from keyboards import get_verify_keyboard, get_meet_keyboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def notify_admins(bot: Bot):
    """Фоновая задача: периодически проверяет новые запросы и уведомляет администраторов."""
    while True:
        try:
            await _send_new_verifications(bot)
            await _send_new_meet_tasks(bot)
        except Exception as e:
            log.error(f"Ошибка в фоновом опросе: {e}")
        await asyncio.sleep(config.POLL_INTERVAL)


async def _send_new_verifications(bot: Bot):
    items = await get_new_pending_verifications()
    for item in items:
        caption = (
            f"Новый запрос на верификацию #{item['id']}\n"
            f"Пользователь: {item['user_id']}\n"
            f"Время: {item['created_at']}"
        )
        # Используем файл с диска, т.к. file_id от другого бота не работает
        photo_path = item.get('photo_path')
        if photo_path and os.path.exists(photo_path):
            photo = FSInputFile(photo_path)
        else:
            photo = item['photo_file_id']
            log.warning(f"Фото для верификации #{item['id']} не найдено на диске, используем file_id (может не сработать)")

        sent = False
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_photo(
                    admin_id,
                    photo=photo,
                    caption=caption,
                    reply_markup=get_verify_keyboard(item['user_id'], item['id']),
                )
                sent = True
            except Exception as e:
                log.warning(f"Не удалось отправить верификацию {item['id']} администратору {admin_id}: {e}")
        if sent:
            await mark_verification_notified(item['id'])


async def _send_new_meet_tasks(bot: Bot):
    tasks = await get_new_meet_tasks_for_admin()
    for task in tasks:
        caption = (
            f"Новая встреча на проверке #{task['id']}\n"
            f"Участники: {task['user1_id']} и {task['user2_id']}\n"
            f"Место: {task['location']}\n"
            f"Институт: {task['institute']}"
        )
        video_path = task.get('video_path')
        if video_path and os.path.exists(video_path):
            video = FSInputFile(video_path)
        elif task.get('video_file_id'):
            video = task['video_file_id']
            log.warning(f"Видео встречи #{task['id']} не найдено на диске, используем file_id (может не сработать)")
        else:
            video = None

        sent = False
        for admin_id in config.ADMIN_IDS:
            try:
                if video:
                    try:
                        await bot.send_video_note(admin_id, video)
                    except Exception as e:
                        log.warning(f"Не удалось отправить видео встречи #{task['id']} администратору {admin_id}: {e}")
                await bot.send_message(
                    admin_id,
                    caption,
                    reply_markup=get_meet_keyboard(task['id']),
                )
                sent = True
            except Exception as e:
                log.warning(f"Не удалось отправить задание {task['id']} администратору {admin_id}: {e}")
        if sent:
            await mark_meet_admin_notified(task['id'])


async def _on_startup(bot: Bot):
    """Запускает фоновую задачу после полного старта polling."""
    asyncio.get_event_loop().create_task(notify_admins(bot))
    log.info("Фоновой опрос БД запущен.")


async def main():
    await init_moderator_tables()
    log.info("Таблицы модератора инициализированы.")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(_on_startup)

    log.info("ModeratorBot запускается...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
