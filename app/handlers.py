import logging

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

import config
from data import (
    get_stats, get_all_profiles_with_rating, get_username,
    get_all_pending_verifications,
    approve_verification, decline_verification,
    get_all_pending_meet_tasks,
    confirm_meet, decline_meet,
)
from keyboards import get_admin_keyboard, get_verify_keyboard, get_meet_keyboard

router = Router()
log = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ---------- Старт ----------

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Доступ только для администраторов.")
        return
    await message.answer("Панель модератора RatingBot.", reply_markup=get_admin_keyboard())


# ---------- Статистика ----------

@router.message(F.text == "Статистика")
async def cmd_stats(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    stats = await get_stats()
    profiles = await get_all_profiles_with_rating()

    lines_male = []
    lines_female = []

    for p in profiles:
        r = p['rating']
        if r == 1.0:
            r_str = "1⭐ (начальный)"
        elif float(r).is_integer():
            r_str = f"{int(r)}⭐"
        else:
            r_str = f"{r:.2f}⭐"

        username = await get_username(bot, p['user_id'])
        line = f"{r_str} {p['name']} ({username})"

        if p['gender'] == 'Парень':
            lines_male.append(line)
        else:
            lines_female.append(line)

    text = (
        f"Статистика RatingBot\n\n"
        f"Всего анкет: {stats['total']}\n"
        f"Парней: {stats['male']}\n"
        f"Девушек: {stats['female']}\n"
        f"Верифицировано: {stats['verified_count']}\n\n"
        f"Встречи подтверждены: {stats['meets_confirmed']}\n"
        f"Встречи на проверке: {stats['meets_pending']}\n"
        f"Верификации в очереди: {stats['verifications_pending']}\n"
    )

    if lines_male:
        text += "\nПарни:\n" + "\n".join(lines_male) + "\n"
    if lines_female:
        text += "\nДевушки:\n" + "\n".join(lines_female)

    # Разбиваем на части по 4096 символов
    for chunk in _split_text(text):
        await message.answer(chunk)


# ---------- Верификации ----------

@router.message(F.text == "Верификации")
async def cmd_verifications(message: Message):
    if not is_admin(message.from_user.id):
        return

    items = await get_all_pending_verifications()
    if not items:
        await message.answer("Нет ожидающих верификаций.")
        return

    await message.answer(f"Запросов на верификацию: {len(items)}")
    for item in items:
        await message.answer_photo(
            photo=item['photo_file_id'],
            caption=f"Верификация #{item['id']}\nПользователь: {item['user_id']}\nВремя: {item['created_at']}",
            reply_markup=get_verify_keyboard(item['user_id'], item['id']),
        )


@router.callback_query(F.data.startswith("mv_ok_"))
async def cb_verify_approve(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    parts = callback.data.split("_")
    user_id = int(parts[2])
    verification_id = int(parts[3])

    await approve_verification(user_id, verification_id)

    try:
        await bot.send_message(user_id, "Ваша верификация одобрена! Вы получили значок верификации.")
    except Exception as e:
        log.warning(f"Не удалось уведомить {user_id}: {e}")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Пользователь верифицирован.")


@router.callback_query(F.data.startswith("mv_no_"))
async def cb_verify_decline(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    parts = callback.data.split("_")
    user_id = int(parts[2])
    verification_id = int(parts[3])

    await decline_verification(verification_id)

    try:
        await bot.send_message(
            user_id,
            "Ваш запрос на верификацию отклонён. Попробуйте снова с более чётким фото студенческого билета."
        )
    except Exception as e:
        log.warning(f"Не удалось уведомить {user_id}: {e}")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Верификация отклонена.")


# ---------- Встречи на проверке ----------

@router.message(F.text == "Встречи на проверке")
async def cmd_pending_meets(message: Message):
    if not is_admin(message.from_user.id):
        return

    tasks = await get_all_pending_meet_tasks()
    if not tasks:
        await message.answer("Нет встреч на проверке.")
        return

    await message.answer(f"Встреч на проверке: {len(tasks)}")
    for task in tasks:
        caption = (
            f"Встреча #{task['id']}\n"
            f"Участники: {task['user1_id']} и {task['user2_id']}\n"
            f"Место: {task['location']}\n"
            f"Институт: {task['institute']}"
        )
        if task.get('video_file_id'):
            await message.answer_video_note(task['video_file_id'])
            await message.answer(caption, reply_markup=get_meet_keyboard(task['id']))
        else:
            await message.answer(
                caption + "\n(видео не прикреплено)",
                reply_markup=get_meet_keyboard(task['id'])
            )


@router.callback_query(F.data.startswith("mm_ok_"))
async def cb_meet_confirm(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    task_id = int(callback.data.split("_")[2])
    result = await confirm_meet(task_id)

    if not result:
        await callback.answer("Задание не найдено или уже обработано.", show_alert=True)
        return

    bonus = f" (x{result['multiplier']} — {result['season_name']})" if result['season_name'] else ""
    text = f"Ваша встреча подтверждена! +{result['points']} очков{bonus}"

    for uid in [result['user1_id'], result['user2_id']]:
        try:
            await bot.send_message(uid, text)
        except Exception as e:
            log.warning(f"Не удалось уведомить {uid}: {e}")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Встреча подтверждена, очки начислены.")


@router.callback_query(F.data.startswith("mm_no_"))
async def cb_meet_decline(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    task_id = int(callback.data.split("_")[2])
    result = await decline_meet(task_id)

    if not result:
        await callback.answer("Задание не найдено или уже обработано.", show_alert=True)
        return

    try:
        await bot.send_message(result['user1_id'], "Ваша встреча не подтверждена администратором. Очки не начислены.")
        await bot.send_message(result['user2_id'], "Встреча не подтверждена администратором.")
    except Exception as e:
        log.warning(f"Ошибка уведомления: {e}")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Встреча отклонена.")


# ---------- Утилиты ----------

def _split_text(text: str, limit: int = 4096):
    return [text[i:i + limit] for i in range(0, len(text), limit)]
