import asyncio
import logging
import time
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database as db

router = Router()

COOLDOWN = 15  # секунд

class Onboarding(StatesGroup):
    viewing = State()


def progress_bar(step: int, total: int = 10) -> str:
    filled = int((step / total) * 10)
    bar = "█" * filled + "░" * (10 - filled)
    pct = int((step / total) * 100)
    return f"[{bar}] {pct}%"


def _build_hierarchy(creator, sup_tags, mentors_raw, moderator, developer) -> str:
    lines = [f"📖 Шаг 2/10 {progress_bar(2)}\n\n👥 <b>Вертикаль обращений — к кому писать</b>\n\nВажно понимать иерархию, чтобы не тратить время зря:\n\n"]
    if creator and creator != "@id":
        lines.append(f"• 👑 Создатель: {creator}\n  └ только критические вопросы\n")
    if sup_tags and sup_tags != "—":
        lines.append(f"• 💎 Саппорты: {sup_tags}\n  └ вопросы по логам\n")
    if mentors_raw and mentors_raw != "@id":
        lines.append(f"• 🎓 Наставники: {mentors_raw}\n  └ обучение, помощь в варке\n")
    if moderator and moderator != "@id":
        lines.append(f"• 🛡 Модератор: {moderator}\n  └ вопросы по чату, небольшие нюансы\n")
    if developer and developer != "@id":
        lines.append(f"• ⚙️ Разработчик/парсер: {developer}\n  └ только сложные кейсы\n")
    lines.append("\n⚡️ <b>Золотое правило:</b> Пиши по делу и строго по своей теме!")
    return "".join(lines)


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
    developer   = await db.get_setting("role_developer") or "@id"
    mentors_raw = await db.get_setting("role_mentors") or "@id"

    steps = {
        1: (
            f"📖 Шаг 1/10 {progress_bar(1)}\n\n"
            "👋 Добро пожаловать в команду!\n\n"
            "Я проведу тебя через короткий, но <b>очень важный</b> инструктаж.\n"
            "Это займёт всего 5-7 минут, но сэкономит часы твоего времени в будущем.\n\n"
            "<b>Что тебя ждёт:</b>\n"
            "• 🎯 7 коротких обучающих шагов\n"
            "• 📝 3 проверочных вопроса (квиз)\n\n"
            "⚠️ <b>Важно:</b> Будь внимателен и не пропускай информацию!\n\n"
            "Готов начать? Жми «Следующий шаг» ⬇️"
        ),
        2: _build_hierarchy(creator, sup_tags, mentors_raw, moderator, developer),
        3: (
            f"📖 Шаг 3/10 {progress_bar(3)}\n\n"
            "⏰ <b>Рабочее время и режим приёма логов</b>\n\n"
            "📅 Наши смены:\n"
            "• ☀️ Дневной ворк: 10:00 – 20:00\n"
            "• 🌙 Ночной ворк: 20:00 – 00:00 и 07:00 – 10:00\n\n"
            "🚦 Режимы бота:\n"
            "• ☀️ «Дневной ворк» — дневная смена активна\n"
            "• 🌙 «Ночной ворк» — ночная смена активна\n"
            "• 🛑 «Стоп» — приём логов приостановлен\n\n"
            "⚠️ <b>Важно:</b>\n"
            "• Логи принимаются ТОЛЬКО во время активной смены\n"
            "• В режиме «Стоп» не передавай логи в бота\n"
            "• Если срочный лог — пиши напрямую саппортам\n\n"
            "💡 Качество варки = 50% успеха!"
        ),
        4: (
            f"📖 Шаг 4/10 {progress_bar(4)}\n\n"
            "🎛 <b>Главное меню бота — твой командный центр</b>\n\n"
            "• 📤 «Передать кошелёк»\n"
            "  └ пошаговая передача логов\n"
            "• 📄 «Мои логи»\n"
            "  └ история переданных логов и их статусы\n"
            "• ✏️ «Изменить тег»\n"
            "  └ настройка твоего уникального ника\n"
            "• 💡 «Полезная информация»\n"
            "  └ доступ к каналам команды\n"
            "• ⭐️ «Оставить отзыв»\n"
            "  └ доступно после 1 засчитанного лога"
        ),
        5: (
            f"📖 Шаг 5/10 {progress_bar(5)}\n\n"
            "💰 <b>Условия выплат за логи</b>\n\n"
            "💵 Базовая ставка: 5 $ за хороший лог\n\n"
            "✅ <b>Требования к логу:</b>\n"
            "• Сумма от 2000 $\n"
            "• Кошелёк не бит\n"
            "• Только TRC-20 сеть\n"
            "• Не рекламный лог\n"
            "• Менее 100 страниц операций\n"
            "• Не обменник\n"
            "• Не в запретной сфере\n"
            "• Сумма сделки ≤ 50% баланса\n\n"
            "📊 <b>Процент от профита:</b>\n"
            f"• Базовый: <b>{int(base_pct)}%</b>\n"
            f"• С наставником: <b>{int(mentor_pct)}%</b> (−10 п.п.)\n\n"
            "💡 Наставник увеличивает количество и качество выплат!"
        ),
        6: (
            f"📖 Шаг 6/10 {progress_bar(6)}\n\n"
            "📚 <b>Информационные каналы</b>\n\n"
            "• 📖 Мануалы — обучающие материалы\n"
            "• 💸 Выплаты — прозрачность выплат\n"
            "• 📁 Документы — шаблоны, скрипты\n"
            "• 💡 Полезная информация — лайфхаки, новости\n\n"
            "🔗 Все ссылки доступны в боте через «💡 Полезная информация»\n\n"
            "⚡️ Подпишись на все каналы — это займёт пару минут!"
        ),
        7: (
            f"📖 Шаг 7/10 {progress_bar(7)}\n\n"
            "🛡 <b>Безопасность и инструменты</b>\n\n"
            "🔐 <b>VPN — обязателен!</b>\n"
            "• Используй @spaacevpn_bot\n"
            "• Скрывает твой реальный IP\n\n"
            "📱 <b>Номера для работы</b>\n"
            "• WhatsApp/Telegram: @qrx_shop_bot\n"
            "• НЕ связывай с личными данными\n\n"
            "⚠️ <b>Правила безопасности:</b>\n"
            "• ❌ Не светить личные данные\n"
            "• ❌ Не переходить по ссылкам от клиентов\n"
            "• ❌ Не использовать личные номера\n"
            "• ✅ Всегда через VPN\n"
            "• ✅ Отдельные аккаунты для работы\n"
            "• ✅ Прокси (@Betternever_findbot) для мультиаккаунтов\n\n"
            "🛡️ Безопасность — залог долгой работы!"
        ),
    }
    return steps.get(step, "")


QUIZ = [
    {
        "step": 8,
        "question": (
            f"📖 Шаг 8/10 {progress_bar(8)}\n\n"
            "📝 <b>Проверка знаний #1</b>\n\n"
            "<b>Вопрос 1 из 3:</b>\n"
            "В какое время работает дневная смена?\n\n"
            "А) 09:00 – 22:00\n"
            "В) 10:00 – 20:00\n"
            "С) 07:00 – 11:00"
        ),
        "correct": "B",
        "correct_text": "В) 10:00 – 20:00",
    },
    {
        "step": 9,
        "question": (
            f"📖 Шаг 9/10 {progress_bar(9)}\n\n"
            "📝 <b>Проверка знаний #2</b>\n\n"
            "<b>Вопрос 2 из 3:</b>\n"
            "Какая минимальная сумма для передачи лога?\n\n"
            "А) 500 $\n"
            "В) 1000 $\n"
            "С) 2000 $"
        ),
        "correct": "C",
        "correct_text": "С) 2000 $",
    },
    {
        "step": 10,
        "question": (
            f"📖 Шаг 10/10 {progress_bar(10)}\n\n"
            "📝 <b>Проверка знаний #3</b>\n\n"
            "<b>Вопрос 3 из 3:</b>\n"
            "Какую сеть кошелька принимает бот?\n\n"
            "А) ERC-20\n"
            "В) BEP-20\n"
            "С) TRC-20"
        ),
        "correct": "C",
        "correct_text": "С) TRC-20",
    },
]

FINISH_TEXT = (
    "🎉 <b>Поздравляем! Ты успешно прошёл инструктаж!</b>\n\n"
    "✅ Все вопросы отвечены верно.\n\n"
    "Теперь ты знаешь:\n"
    "• Как и к кому обращаться\n"
    "• Когда принимаются логи\n"
    "• Как работает система выплат\n"
    "• Как оставаться в безопасности\n\n"
    "🚀 <b>Удачи в работе! Команда верит в тебя.</b>\n\n"
    "Возвращайся в главное меню и начинай работать 💪"
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
    started_at = data.get("started_at", 0)
    elapsed = time.time() - started_at

    if elapsed < COOLDOWN:
        remaining = int(COOLDOWN - elapsed)
        await call.answer(f"Подождите ещё {remaining} сек.", show_alert=True)
        return

    await call.answer()

    # Удаляем текущее сообщение
    try:
        await call.message.delete()
    except Exception:
        pass

    next_step = current_step + 1

    if next_step <= 7:
        text = await get_step_text(next_step)
        await call.message.answer(text, parse_mode="HTML", reply_markup=kb_next(next_step))
        await state.update_data(step=next_step, started_at=time.time())
    else:
        quiz = QUIZ[0]
        await state.update_data(step=8, quiz_idx=0, started_at=time.time())
        await call.message.answer(quiz["question"] + "\n\nВыбери правильный вариант ⬇️", parse_mode="HTML", reply_markup=kb_quiz(8))


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
        # Удаляем текущее сообщение
        try:
            await call.message.delete()
        except Exception:
            pass

        if quiz_idx < 2:
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
        # При неверном ответе не удаляем, просто показываем правильный
        await call.message.answer(
            f"❌ <b>Неверно.</b>\n\nПравильный ответ: <b>{quiz['correct_text']}</b>\n\nПопробуй ещё раз:",
            parse_mode="HTML",
            reply_markup=kb_quiz(step),
        )
