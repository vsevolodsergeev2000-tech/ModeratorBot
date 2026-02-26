from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Статистика"), KeyboardButton(text="Верификации")],
            [KeyboardButton(text="Встречи на проверке")],
        ],
        resize_keyboard=True,
    )


def get_verify_keyboard(user_id: int, verification_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Одобрить",
            callback_data=f"mv_ok_{user_id}_{verification_id}"
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=f"mv_no_{user_id}_{verification_id}"
        ),
    ]])


def get_meet_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Подтвердить",
            callback_data=f"mm_ok_{task_id}"
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=f"mm_no_{task_id}"
        ),
    ]])
