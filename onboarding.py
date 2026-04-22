import time
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database as db

router = Router()

COOLDOWN = 10  # секунд между шагами

TOTAL_STEPS = 6
TOTAL_QUIZ = 2


class Onboarding(StatesGroup):
    viewing = State()


def progress_bar(step: int, total: int = TOTAL_STEPS + TOTAL_QUIZ) -> str:
    filled = int((step / total) * 10)
    bar = "█" * filled + "░" * (10 - filled)
    pct = int((step / total) * 100)
    return f"[{bar}] {pct}%"


async def get_step_text(step: int) -> str:
    pct = await db.get_setting("default_pct")
    try:
        base_pct = float(pct) if pct else 60.0
    except Exception:
        base_pct = 60.0
    mentor_pct = base_pct - 10

    supports = await db.get_supports_on_shift()
    sup_tags = " ".join([f"@{s['username']}" for s in supports if s.get("username")]) or "—"

    creator     = await db.get_setting("role_creator") or "@id"
    moderator   = await db.get_setting("role_moderator") or "@id"
    mentors_raw = await db.get_setting("role_mentors") or "@id"

    steps = {
        1: (
            f"📖 Шаг 1/{TOTAL_STEPS} {progress_bar(1)}\n\n"
            "👋 <b>Добро пожаловать в команду!</b>\n\n"
            "Я проведу тебя через короткий инструктаж — это займёт всего несколько минут.\n\n"
            "<b>Что тебя ждёт:</b>\n"
            f"• 📚 {TOTAL_STEPS} обучающих шагов\n"
            f"• 📝 {TOTAL_QUIZ} проверочных вопроса\n\n"
            "⚠️ <b>Читай внимательно — от этого зависит твой результат!</b>\n\n"
            "Готов? Жми «Следующий шаг» ⬇️"
        ),
        2: (
            f"📖 Шаг 2/{TOTAL_STEPS} {progress_bar(2)}\n\n"
            "👥 <b>Иерархия команды</b>\n\n"
            "Важно знать к кому и по каким вопросам обращаться:\n\n"
            + (f"• 👑 Создатель: {creator}\n  └ только критические вопросы\n" if creator != "@id" else "")
            + (f"• 💎 Саппорты: {sup_tags}\n  └ вопросы по чекам и работе\n" if sup_tags != "—" else "")
            + (f"• 🎓 Наставники: {mentors_raw}\n  └ обучение и помощь\n" if mentors_raw != "@id" else "")
            + (f"• 🛡 Модератор: {moderator}\n  └ вопросы по чату\n" if moderator != "@id" else "")
            + "\n⚡️ <b>Золотое правило:</b> пиши по делу и строго по своей теме!"
        ),
        3: (
            f"📖 Шаг 3/{TOTAL_STEPS} {progress_bar(3)}\n\n"
            "⏰ <b>Режим работы</b>\n\n"
            "📅 Наши смены:\n"
            "• ☀️ Дневной ворк: 10:00 – 20:00\n"
            "• 🌙 Ночной ворк: 20:00 – 00:00 и 07:00 – 10:00\n\n"
            "🚦 Статусы бота:\n"
            "• ☀️ <b>Дневной ворк</b> — смена активна\n"
            "• 🌙 <b>Ночной ворк</b> — смена активна\n"
            "• 🔴 <b>Стоп</b> — работа приостановлена\n\n"
            "⚠️ Создавай чеки только во время активной смены.\n"
            "Если срочный вопрос — пиши саппортам напрямую."
        ),
        4: (
            f"📖 Шаг 4/{TOTAL_STEPS} {progress_bar(4)}\n\n"
            "🧾 <b>Как работают чеки</b>\n\n"
            "Создать чек можно на любую сумму.\n\n"
            "⚠️ <b>Важно знать перед отправкой клиенту:</b>\n\n"
            "• Чеки работают только с <b>USDT TRC-20</b>\n\n"
            "• Убедись, что у клиента <b>WEB3-кошелёк</b> (Trust Wallet, MetaMask и т.д.)\n\n"
            "• Если у клиента <b>биржа</b> — он не сможет подключить кошелёк.\n"
            "  └ Попроси перенести кошелёк по сид-фразе в <b>Trust Wallet</b>\n"
            "  └ После этого он сможет подключиться к системе\n\n"
            "• Если клиент не хочет переносить — попроси <b>другой кошелёк</b>.\n"
            "  └ Скажи, что у тебя выдаёт ошибку при переводе на его адрес\n\n"
            "💡 <b>Правило:</b> клиент должен иметь WEB3-кошелёк — это обязательное условие."
        ),
        5: (
            f"📖 Шаг 5/{TOTAL_STEPS} {progress_bar(5)}\n\n"
            "💰 <b>Система выплат</b>\n\n"
            f"📊 Твой процент от профита: <b>{int(base_pct)}%</b>\n"
            + (f"📊 С наставником: <b>{int(mentor_pct)}%</b> (−10 п.п.)\n\n" if mentor_pct != base_pct else "\n")
            + "💸 Выплаты производятся администратором вручную.\n\n"
            "🤝 <b>Наставник</b> — опытный участник команды, который поможет тебе:\n"
            "• Быстрее освоиться\n"
            "• Увеличить количество успешных сделок\n"
            "• Разобраться в сложных ситуациях\n\n"
            "Наставник работает с тобой на протяжении <b>5 выплат</b>.\n"
            "Выбрать наставника можно в разделе «🎓 Наставники»."
        ),
        6: (
            f"📖 Шаг 6/{TOTAL_STEPS} {progress_bar(6)}\n\n"
            "🛡 <b>Безопасность</b>\n\n"
            "🔐 <b>VPN — обязателен!</b>\n"
            "• Используй @spaacevpn_bot\n"
            "• Скрывает твой реальный IP\n\n"
            "📱 <b>Номера для работы:</b>\n"
            "• WhatsApp/Telegram: @qrx_shop_bot\n"
            "• Не используй личные номера\n\n"
            "⚠️ <b>Правила:</b>\n"
            "• ❌ Не раскрывай личные данные\n"
            "• ❌ Не переходи по ссылкам от клиентов\n"
            "• ✅ Работай только через VPN\n"
            "• ✅ Используй отдельные аккаунты для работы\n\n"
            "🛡 Безопасность — залог долгой и стабильной работы!"
        ),
    }
    return steps.get(step, "")


QUIZ = [
    {
        "step": TOTAL_STEPS + 1,
        "question": (
            f"📝 Вопрос 1/2 {progress_bar(TOTAL_STEPS + 1)}\n\n"
            "<b>Что нужно клиенту для работы с чеком?</b>\n\n"
            "А) Аккаунт на бирже\n"
            "В) WEB3-кошелёк (например Trust Wallet)\n"
            "С) Банковская карта"
        ),
        "correct": "B",
        "correct_text": "В) WEB3-кошелёк (например Trust Wallet)",
    },
    {
        "step": TOTAL_STEPS + 2,
        "question": (
            f"📝 Вопрос 2/2 {progress_bar(TOTAL_STEPS + 2)}\n\n"
            "<b>С какой сетью работают чеки?</b>\n\n"
            "А) ERC-20\n"
            "В) BEP-20\n"
            "С) TRC-20 (USDT)"
        ),
        "correct": "C",
        "correct_text": "С) TRC-20 (USDT)",
    },
]

FINISH_TEXT = (
    "🎉 <b>Инструктаж пройден!</b>\n\n"
    "✅ Все вопросы отвечены верно.\n\n"
    "<b>Ты знаешь:</b>\n"
    "• Как устроена команда и к кому обращаться\n"
    "• Как работают чеки и что нужно клиенту\n"
    "• Как работает система выплат\n"
    "• Как оставаться в безопасности\n\n"
    "🚀 <b>Удачи в работе! Команда верит в тебя.</b>\n\n"
    "Возвращайся в главное меню и начинай 💪"
)


def kb_next(step: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Следующий шаг", callback_data=f"ob_next:{step}")]
    ])


def kb_quiz(step: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="А", callback_data=f"ob_quiz:{step}:A"),
            InlineKeyboardButton(text="В", callback_data=f"ob_quiz:{step}:B"),
            InlineKeyboardButton(text="С", callback_data=f"ob_quiz:{step}:C"),
        ]
    ])


async def start_onboarding(message: Message, state: FSMContext):
    await state.set_state(Onboarding.viewing)
    await state.update_data(step=1, started_at=time.time(), quiz_idx=0)
    text = await get_step_text(1)
    await message.answer(text, parse_mode="HTML", reply_markup=kb_next(1))


@router.callback_query(Onboarding.viewing, F.data.startswith("ob_next:"))
async def ob_next(call: CallbackQuery, state: FSMContext):
    current_step = int(call.data.split(":")[1])
    data = await state.get_data()
    elapsed = time.time() - data.get("started_at", 0)

    if elapsed < COOLDOWN:
        remaining = int(COOLDOWN - elapsed)
        await call.answer(f"Подождите ещё {remaining} сек.", show_alert=True)
        return

    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass

    next_step = current_step + 1

    if next_step <= TOTAL_STEPS:
        text = await get_step_text(next_step)
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb_next(next_step))
        await state.update_data(step=next_step, started_at=time.time())
    else:
        quiz = QUIZ[0]
        await state.update_data(step=TOTAL_STEPS + 1, quiz_idx=0, started_at=time.time())
        await call.message.answer(
            quiz["question"] + "\n\nВыбери правильный вариант ⬇️",
            parse_mode="HTML",
            reply_markup=kb_quiz(TOTAL_STEPS + 1),
        )


@router.callback_query(Onboarding.viewing, F.data.startswith("ob_quiz:"))
async def ob_quiz(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    step = int(parts[1])
    answer = parts[2]

    data = await state.get_data()
    quiz_idx = data.get("quiz_idx", 0)
    quiz = QUIZ[quiz_idx]

    await call.answer()

    if answer == quiz["correct"]:
        try:
            await call.message.delete()
        except Exception:
            pass

        if quiz_idx < len(QUIZ) - 1:
            next_quiz = QUIZ[quiz_idx + 1]
            await state.update_data(quiz_idx=quiz_idx + 1)
            await call.message.answer(
                "✅ <b>Верно!</b>\n\n" + next_quiz["question"] + "\n\nВыбери правильный вариант ⬇️",
                parse_mode="HTML",
                reply_markup=kb_quiz(next_quiz["step"]),
            )
        else:
            await db.set_onboarding_done(call.from_user.id)
            await state.clear()
            await call.message.answer(
                "✅ <b>Верно!</b>\n\n" + FINISH_TEXT,
                parse_mode="HTML",
            )
    else:
        await call.message.answer(
            f"❌ <b>Неверно.</b>\n\nПравильный ответ: <b>{quiz['correct_text']}</b>\n\nПопробуй ещё раз:",
            parse_mode="HTML",
            reply_markup=kb_quiz(step),
        )
