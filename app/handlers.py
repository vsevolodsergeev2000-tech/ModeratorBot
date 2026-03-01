import html
import logging
import os

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile

import config
from data import (
    get_stats, get_all_profiles_with_rating, get_username,
    get_all_pending_verifications, get_user_id_by_verification,
    approve_verification, decline_verification,
    get_all_pending_meet_tasks,
    confirm_meet, decline_meet,
)
from keyboards import get_admin_keyboard, get_verify_keyboard, get_meet_keyboard

# Базовые каталоги для медиафайлов (защита от path traversal)
_DB_DIR = os.path.dirname(os.path.abspath(config.DB_PATH))
_VERIF_BASE = os.path.join(_DB_DIR, 'verif_photos')
_MEETS_BASE = os.path.join(_DB_DIR, 'meet_videos')


def _safe_path(path: str, base_dir: str) -> str | None:
    """Возвращает path если он находится внутри base_dir, иначе None."""
    if not path:
        return None
    real = os.path.realpath(path)
    real_base = os.path.realpath(base_dir)
    return real if real.startswith(real_base + os.sep) or real == real_base else None

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
        line = f"{r_str} {html.escape(p['name'])} ({html.escape(username)})"

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
        raw_path = item.get('photo_path')
        safe = _safe_path(raw_path, _VERIF_BASE) if raw_path else None
        photo = FSInputFile(safe) if safe and os.path.exists(safe) else item['photo_file_id']
        await message.answer_photo(
            photo=photo,
            caption=f"Верификация #{item['id']}\nПользователь: {item['user_id']}\nВремя: {item['created_at']}",
            reply_markup=get_verify_keyboard(item['user_id'], item['id']),
        )


@router.callback_query(F.data.startswith("mv_ok_"))
async def cb_verify_approve(callback: CallbackQuery, rating_bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    parts = callback.data.split("_")
    try:
        verification_id = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    # Получаем user_id из БД — не доверяем callback_data
    user_id = await get_user_id_by_verification(verification_id)
    if not user_id:
        await callback.answer("Верификация не найдена.", show_alert=True)
        return

    approved = await approve_verification(user_id, verification_id)
    if not approved:
        await callback.answer("Уже обработано.", show_alert=True)
        return

    try:
        await rating_bot.send_message(user_id, "Ваша верификация одобрена! Вы получили значок верификации.")
    except Exception as e:
        log.warning(f"Не удалось уведомить {user_id}: {e}")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Пользователь верифицирован.")


@router.callback_query(F.data.startswith("mv_no_"))
async def cb_verify_decline(callback: CallbackQuery, rating_bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    parts = callback.data.split("_")
    try:
        verification_id = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    # Получаем user_id из БД — не доверяем callback_data
    user_id = await get_user_id_by_verification(verification_id)
    if not user_id:
        await callback.answer("Верификация не найдена.", show_alert=True)
        return

    await decline_verification(verification_id)

    try:
        await rating_bot.send_message(
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
        raw_vpath = task.get('video_path')
        safe_vpath = _safe_path(raw_vpath, _MEETS_BASE) if raw_vpath else None
        if safe_vpath and os.path.exists(safe_vpath):
            await message.answer_video_note(FSInputFile(safe_vpath))
        elif task.get('video_file_id'):
            try:
                await message.answer_video_note(task['video_file_id'])
            except Exception:
                caption += "\n(видео недоступно)"
        else:
            caption += "\n(видео не прикреплено)"
        await message.answer(caption, reply_markup=get_meet_keyboard(task['id']))


@router.callback_query(F.data.startswith("mm_ok_"))
async def cb_meet_confirm(callback: CallbackQuery, rating_bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    try:
        task_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    result = await confirm_meet(task_id)

    if not result:
        await callback.answer("Задание не найдено или уже обработано.", show_alert=True)
        return

    bonus = f" (x{result['multiplier']} — {result['season_name']})" if result['season_name'] else ""
    text = f"Ваша встреча подтверждена! +{result['points']} очков{bonus}"

    for uid in [result['user1_id'], result['user2_id']]:
        try:
            await rating_bot.send_message(uid, text)
        except Exception as e:
            log.warning(f"Не удалось уведомить {uid}: {e}")

    # Удаляем видеофайл с диска после подтверждения
    if result.get('video_path'):
        safe_vpath = _safe_path(result['video_path'], _MEETS_BASE)
        if safe_vpath and os.path.exists(safe_vpath):
            try:
                os.remove(safe_vpath)
            except OSError as e:
                log.warning(f"Не удалось удалить видео {safe_vpath}: {e}")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Встреча подтверждена, очки начислены.")


@router.callback_query(F.data.startswith("mm_no_"))
async def cb_meet_decline(callback: CallbackQuery, rating_bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав.", show_alert=True)
        return

    try:
        task_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    result = await decline_meet(task_id)

    if not result:
        await callback.answer("Задание не найдено или уже обработано.", show_alert=True)
        return

    try:
        await rating_bot.send_message(result['user1_id'], "Ваша встреча не подтверждена администратором. Очки не начислены.")
    except Exception as e:
        log.warning(f"Не удалось уведомить {result['user1_id']}: {e}")
    try:
        await rating_bot.send_message(result['user2_id'], "Встреча не подтверждена администратором.")
    except Exception as e:
        log.warning(f"Не удалось уведомить {result['user2_id']}: {e}")

    # Удаляем видеофайл с диска после отклонения
    if result.get('video_path'):
        safe_vpath = _safe_path(result['video_path'], _MEETS_BASE)
        if safe_vpath and os.path.exists(safe_vpath):
            try:
                os.remove(safe_vpath)
            except OSError as e:
                log.warning(f"Не удалось удалить видео {safe_vpath}: {e}")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Встреча отклонена.")


# ---------- Утилиты ----------

def _split_text(text: str, limit: int = 4096):
    return [text[i:i + limit] for i in range(0, len(text), limit)]
