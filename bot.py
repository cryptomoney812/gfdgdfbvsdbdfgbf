import asyncio
import logging
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from config import ADMIN_CHAT_ID, ADMIN_IDS, BOT_TOKEN, RESERVE_CHANNEL
import database as db
from onboarding import router as onboarding_router, start_onboarding

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(onboarding_router)

# ─── Global ban middleware ────────────────────────────────────────────────────

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Any, Callable, Awaitable

class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]], event: TelegramObject, data: dict) -> Any:
        user = data.get("event_from_user")
        if user and await db.is_banned(user.id):
            return  # Полностью игнорируем
        return await handler(event, data)

dp.message.middleware(BanMiddleware())
dp.callback_query.middleware(BanMiddleware())

PAYOUTS_CHANNEL = -1003840310493
SUPPORT_CHAT_ID = -5285318192
WORKERS_CHAT_ID = -1003986458830
LOGS_PER_PAGE = 5


# ─── FSM ─────────────────────────────────────────────────────────────────────

class ChangeTag(StatesGroup):
    waiting = State()

class LogFSM(StatesGroup):
    wallet = State()
    deal_scope = State()
    deal_amount = State()
    wallet_balance = State()
    wallet_type = State()
    gender = State()
    language = State()
    country = State()
    contact = State()
    messenger = State()
    client_contact = State()
    extra_yn = State()
    extra_info = State()

class RejectLog(StatesGroup):
    reason = State()

class CheckPhone(StatesGroup):
    waiting = State()

class Broadcast(StatesGroup):
    waiting = State()

class Leavementor(StatesGroup):
    reason = State()

class InvoiceFSM(StatesGroup):
    amount = State()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_trc20(address: str) -> bool:
    return bool(re.match(r'^T[1-9A-HJ-NP-Za-km-z]{33}$', address.strip()))

def fmt(n): return f"{n:,.2f}".replace(",", " ")

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="📤 Передать кошелёк"), KeyboardButton(text="📚 Пройти инструктаж")],
            [KeyboardButton(text="📋 Мои логи"), KeyboardButton(text="💡 Полезная информация")],
            [KeyboardButton(text="🎓 Наставники"), KeyboardButton(text="📡 Резервный канал")],
            [KeyboardButton(text="🧾 Создать чек")],
        ],
        resize_keyboard=True,
    )

def kb_cancel():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)

def kb_profile_inline(has_mentor: bool = False):
    buttons = [[InlineKeyboardButton(text="✏️ Изменить тег", callback_data="change_tag")]]
    if has_mentor:
        buttons.append([InlineKeyboardButton(text="🚪 Уйти от наставника", callback_data="leave_mentor")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_useful_info():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Мануалы",                      callback_data="info_manuals")],
        [InlineKeyboardButton(text="💸 Выплаты",                      callback_data="info_payouts")],
        [InlineKeyboardButton(text="🛠 Техническая поддержка",        callback_data="info_support")],
        [InlineKeyboardButton(text="📢 Канал с полезной информацией", callback_data="info_channel")],
        [InlineKeyboardButton(text="📄 Документы",                    callback_data="info_docs")],
        [InlineKeyboardButton(text="🔧 Инструменты",                  callback_data="info_tools")],
    ])

def kb_tools():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Проверить номер",      callback_data="tool_phone")],
        [InlineKeyboardButton(text="🔍 Чекер кошельков", url="https://t.me/cryptoteamcheacker_bot")],
        [InlineKeyboardButton(text="◀️ Назад",                callback_data="tools_back")],
    ])

def kb_wallet_type():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный", callback_data="wtype_personal")],
        [InlineKeyboardButton(text="🏦 Биржа",  callback_data="wtype_exchange")],
    ])

def kb_gender():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧔 Мужчина", callback_data="gender_male")],
        [InlineKeyboardButton(text="👩 Женщина", callback_data="gender_female")],
    ])

def kb_messenger():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Telegram",  callback_data="msg_telegram")],
        [InlineKeyboardButton(text="WhatsApp",  callback_data="msg_whatsapp")],
        [InlineKeyboardButton(text="Instagram", callback_data="msg_instagram")],
    ])

def kb_extra_yn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да",  callback_data="extra_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="extra_no")],
    ])

def kb_log_admin(log_number: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Взять",    callback_data=f"log_take:{log_number}"),
            InlineKeyboardButton(text="❌ Не брать", callback_data=f"log_skip:{log_number}"),
        ],
    ])

def kb_log_result(log_number: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Успешный",    callback_data=f"log_success:{log_number}")],
        [InlineKeyboardButton(text="❌ Неуспешный",  callback_data=f"log_fail:{log_number}")],
        [InlineKeyboardButton(text="🚫 Не валидный", callback_data=f"log_invalid:{log_number}")],
    ])

def kb_logs_page(logs: list, page: int, total: int):
    rows = []
    status_icons = {"pending": "⏳", "taken": "🔄", "success": "✅", "fail": "❌", "invalid": "🚫"}
    for log in logs:
        icon = status_icons.get(log["status"], "▪️")
        rows.append([InlineKeyboardButton(text=f"{icon} Лог #{log['log_number']}", callback_data=f"log_view:{log['log_number']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"logs_page:{page-1}"))
    total_pages = max(1, (total + LOGS_PER_PAGE - 1) // LOGS_PER_PAGE)
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if (page + 1) * LOGS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"logs_page:{page+1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_log_back():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="logs_page:0")]])

async def build_profile_text(user: dict) -> str:
    work_mode    = await db.get_setting("work_mode")
    project_cash = await db.get_setting("project_cash")
    if user["mentor_id"]:
        mentor = await db.get_mentor(user["mentor_id"])
        mentor_str = f"@{mentor['username']}" if mentor else "—"
        left = user.get("mentor_payouts_left", 0)
        mentor_str += f" (осталось выплат: {left})"
    else:
        mentor_str = "❌"
    supports = await db.get_supports_on_shift()
    sup_lines = "\n".join(f"▪️ @{s['username']}" for s in supports if s.get("username")) or "▪️ Нет саппортов на смене"
    icon = "🌅" if "Дневной" in work_mode else "🌙" if "Ночной" in work_mode else "🔴"
    return (
        f"{icon} <b>{work_mode}</b>\n\n"
        f"👤 <b>Ваш профиль</b>\n\n"
        f"⭐️ Ваш тег: <b>{user['tag']}</b>\n"
        f"🧾 Количество выплат: <b>{user['payout_count']}</b>\n"
        f"💰 Сумма выплат: <b>{user['payout_sum']} USDT</b>\n"
        f"🤝 Наставник: <b>{mentor_str}</b>\n"
        f"📊 Процент выплат: <b>{int(user['payout_pct'])}%</b>\n"
        f"🏦 Касса проекта: <b>{project_cash} USDT</b>\n"
        f"📋 Логов сдано: <b>{user.get('log_count', 0)}</b>\n\n"
        f"🟢 Саппорты в сети:\n{sup_lines}"
    )

async def send_invite(call: CallbackQuery, chat_id: int, label: str):
    try:
        invite = await bot.create_chat_invite_link(chat_id, member_limit=1, expire_date=int(datetime.now().timestamp()) + 300)
        await call.message.answer(
            f"🔗 Ссылка на «<b>{label}</b>»:\n\n{invite.invite_link}\n\n⏳ Ссылка действует <b>5 минут</b> и рассчитана на <b>1 вступление</b>.",
            parse_mode="HTML",
        )
    except Exception as e:
        await call.message.answer(f"❌ Ошибка: {e}")
    await call.answer()

def format_top(rows: list, title: str) -> str:
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    if not rows:
        return f"{title}\n\nПока нет данных."
    text = f"{title}\n\n"
    for i, row in enumerate(rows, 1):
        medal = medals.get(i, f"{i}.")
        val = row.get("payout_sum", row.get("total", 0))
        text += f"{medal} <b>{row['tag']}</b> — {val:.2f} USDT\n"
    return text

def format_top_detailed(rows: list, title: str, period: bool = False) -> str:
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    if not rows:
        return f"{title}\n\nПока нет данных."
    text = f"{title}\n━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(rows, 1):
        medal = medals.get(i, f"{i}.")
        if period:
            val = row.get("total", 0)
            cnt = row.get("payout_count", 0)
            text += f"{medal} <b>{row['tag']}</b>\n   💰 {val:.2f} USDT | 🧾 {cnt} выплат\n"
        else:
            val = row.get("payout_sum", 0)
            cnt = row.get("payout_count", 0)
            text += f"{medal} <b>{row['tag']}</b>\n   💰 {val:.2f} USDT | 🧾 {cnt} выплат\n"
    return text


# ─── /start ──────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    await state.clear()
    if await db.is_banned(message.from_user.id):
        await message.answer("🚫 <b>Вы заблокированы.</b>\n\nОбратитесь к администратору.", parse_mode="HTML"); return
    if not await db.is_approved(message.from_user.id):
        await message.answer("🚫 <b>Доступ закрыт.</b>\n\nПодать заявку: @cryptobot_teambot", parse_mode="HTML"); return
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.full_name)
    work_mode = await db.get_setting("work_mode")
    icon = "🌅" if "Дневной" in work_mode else "🌙" if "Ночной" in work_mode else "🔴"
    await message.answer(
        f"{icon} <b>{work_mode}</b>\n\nДобро пожаловать, <b>{user['tag']}</b>!\nИспользуй меню ниже.",
        reply_markup=main_menu(), parse_mode="HTML",
    )


# ─── Профиль ─────────────────────────────────────────────────────────────────

@dp.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.full_name)
    text = await build_profile_text(user)
    await message.answer(text, parse_mode="HTML", reply_markup=kb_profile_inline(has_mentor=bool(user.get("mentor_id"))))


# ─── Изменить тег ─────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "change_tag")
async def change_tag_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("✏️ Введите новый тег:\n\n▪️ Только латинские буквы и цифры\n▪️ Максимум 12 символов", reply_markup=kb_cancel())
    await call.answer(); await state.set_state(ChangeTag.waiting)

@dp.message(ChangeTag.waiting, F.text == "❌ Отмена")
async def change_tag_cancel(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(ChangeTag.waiting)
async def change_tag_process(message: Message, state: FSMContext):
    tag = message.text.strip()
    if not tag.isascii() or not tag.replace("_", "").isalnum():
        await message.answer("❌ Только латинские буквы и цифры. Попробуй снова:"); return
    if len(tag) > 12:
        await message.answer("❌ Максимум 12 символов. Попробуй снова:"); return
    ok = await db.update_tag(message.from_user.id, tag)
    if not ok:
        await message.answer("❌ Этот тег уже занят. Введи другой:"); return
    await state.clear()
    await message.answer(f"✅ Тег изменён на <b>{tag}</b>", parse_mode="HTML", reply_markup=main_menu())


# ─── Наставники ───────────────────────────────────────────────────────────────

@dp.message(F.text == "🎓 Наставники")
async def mentors_list(message: Message):
    mentors = await db.get_all_mentors()
    if not mentors:
        await message.answer("🎓 Список наставников пуст."); return
    buttons = [[InlineKeyboardButton(text=f"🎓 @{m['username']} ({m['tag']})", callback_data=f"mentor_view:{m['user_id']}")] for m in mentors]
    await message.answer(
        "🎓 <b>Список наставников</b>\n\nВыберите наставника чтобы узнать подробнее:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )

@dp.callback_query(F.data.startswith("mentor_view:"))
async def mentor_view(call: CallbackQuery):
    mentor_id = int(call.data.split(":")[1])
    mentor = await db.get_mentor(mentor_id)
    if not mentor:
        await call.answer("Наставник не найден.", show_alert=True); return
    user = await db.get_user(call.from_user.id)
    already_has = user and user.get("mentor_id") == mentor_id
    bio = f"\n\n📝 {mentor['bio']}" if mentor.get("bio") else ""
    text = (
        f"🎓 <b>Наставник @{mentor['username']}</b>\n\n"
        f"⭐️ Тег: <b>{mentor['tag']}</b>\n"
        f"👥 Учеников: <b>{mentor['student_count']}</b>\n"
        f"💰 Выплат проведено: <b>{mentor['payout_count']}</b>\n"
        f"💵 Заработано: <b>{mentor['payout_sum']:.2f} USDT</b>\n"
        f"📊 Процент за 5 выплат: <b>{mentor['fee_pct']}%</b>"
        f"{bio}"
    )
    buttons = []
    if not already_has and user and not user.get("mentor_id"):
        buttons.append([InlineKeyboardButton(text="✅ Выбрать наставника", callback_data=f"mentor_choose:{mentor_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="mentors_back")])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()

@dp.callback_query(F.data == "mentors_back")
async def mentors_back(call: CallbackQuery):
    mentors = await db.get_all_mentors()
    buttons = [[InlineKeyboardButton(text=f"🎓 @{m['username']} ({m['tag']})", callback_data=f"mentor_view:{m['user_id']}")] for m in mentors]
    await call.message.edit_text(
        "🎓 <b>Список наставников</b>\n\nВыберите наставника чтобы узнать подробнее:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await call.answer()

@dp.callback_query(F.data.startswith("mentor_choose:"))
async def mentor_choose(call: CallbackQuery):
    mentor_id = int(call.data.split(":")[1])
    user = await db.get_user(call.from_user.id)
    if user and user.get("mentor_id"):
        await call.answer("У вас уже есть наставник.", show_alert=True); return
    await db.assign_mentor(call.from_user.id, mentor_id)
    mentor = await db.get_mentor(mentor_id)
    await call.message.edit_text(
        f"✅ <b>Вы выбрали наставника @{mentor['username']}!</b>\n\nНаставник будет работать с вами на протяжении 5 выплат.\nПроцент наставника: <b>{mentor['fee_pct']}%</b>",
        parse_mode="HTML",
    )
    await call.answer()
    try:
        await bot.send_message(
            mentor_id,
            f"🎓 <b>Новый ученик!</b>\n\nПользователь <b>{user['tag']}</b> выбрал вас наставником.",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ─── Уйти от наставника ───────────────────────────────────────────────────────

@dp.callback_query(F.data == "leave_mentor")
async def leave_mentor_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Укажите причину отказа от наставника:", reply_markup=kb_cancel())
    await call.answer(); await state.set_state(Leavementor.reason)

@dp.message(Leavementor.reason, F.text == "❌ Отмена")
async def leave_mentor_cancel(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(Leavementor.reason)
async def leave_mentor_send(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    mentor = await db.get_mentor(user["mentor_id"]) if user and user.get("mentor_id") else None
    mentor_str = f"@{mentor['username']}" if mentor else "—"
    await message.answer("✅ Запрос отправлен администратору. Ожидайте решения.", reply_markup=main_menu())
    await bot.send_message(
        ADMIN_CHAT_ID,
        f"🚪 <b>Запрос на отказ от наставника</b>\n\n"
        f"👤 Пользователь: <b>{user['tag']}</b> | <code>{message.from_user.id}</code>\n"
        f"🎓 Наставник: {mentor_str}\n\n"
        f"📝 Причина: {message.text}\n\n"
        f"Для отвязки: /delmentor {user['tag']}",
        parse_mode="HTML",
    )


# ─── Инструктаж ───────────────────────────────────────────────────────────────

@dp.message(F.text == "📚 Пройти инструктаж")
async def instructions(message: Message, state: FSMContext):
    if await db.is_onboarding_done(message.from_user.id):
        await message.answer("✅ <b>Вы уже прошли инструктаж.</b>\n\nЕсли есть вопросы — обратитесь к наставнику или саппорту.", parse_mode="HTML"); return
    await start_onboarding(message, state)


# ─── Топ ─────────────────────────────────────────────────────────────────────

@dp.message(Command("top"))
async def cmd_top(message: Message):
    rows = await db.get_top_all()
    cash = await db.get_setting("project_cash")
    text = format_top_detailed(rows, "🏆 <b>Топ воркеров — Все время</b>")
    text += f"\n\n🏦 <b>Общая касса проекта: {cash} USDT</b>"
    await message.answer(text, parse_mode="HTML")








# ─── Мои логи ─────────────────────────────────────────────────────────────────

@dp.message(F.text == "📋 Мои логи")
async def my_logs(message: Message):
    logs, total = await db.get_user_logs_page(message.from_user.id, 0)
    if not logs:
        await message.answer("📋 У вас пока нет логов."); return
    await message.answer(
        f"📋 <b>Ваши логи</b> (всего: {total}):\n\nНажмите на лог чтобы посмотреть детали:",
        parse_mode="HTML", reply_markup=kb_logs_page(logs, 0, total),
    )

@dp.callback_query(F.data.startswith("logs_page:"))
async def logs_page_cb(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    logs, total = await db.get_user_logs_page(call.from_user.id, page)
    await call.message.edit_text(
        f"📋 <b>Ваши логи</b> (всего: {total}):\n\nНажмите на лог чтобы посмотреть детали:",
        parse_mode="HTML", reply_markup=kb_logs_page(logs, page, total),
    )
    await call.answer()

@dp.callback_query(F.data.startswith("log_view:"))
async def log_view(call: CallbackQuery):
    log_number = call.data.split(":")[1]
    log = await db.get_log(log_number)
    if not log:
        await call.answer("Лог не найден.", show_alert=True); return
    status_map = {"pending": "⏳ На рассмотрении", "taken": "🔄 В обработке", "success": "✅ Успешный", "fail": "❌ Неуспешный", "invalid": "🚫 Не валидный"}
    status = status_map.get(log["status"], log["status"])
    support_info = f"\n👮 Саппорт: @{log['support_username']}" if log.get("support_username") else ""
    extra = f"\n📝 Доп. инфо: {log['extra_info']}" if log.get("extra_info") else ""
    text = (
        f"📋 <b>Лог #{log['log_number']}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📅 {log['created_at']}\n"
        f"💼 <code>{log['wallet']}</code>\n"
        f"🔖 {log['wallet_type']} | 💰 {log['wallet_balance']} USDT\n"
        f"📦 {log['deal_scope']} | 💵 {log['deal_amount']} USDT\n"
        f"🌐 {log['language']} | 🌍 {log['country']}\n"
        f"📱 {log['messenger']}: {log['client_contact']}{extra}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Статус: {status}{support_info}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_log_back())
    await call.answer()

@dp.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


# ════════════════════════════════════════════════════════════════════════════
# ПЕРЕДАТЬ КОШЕЛЁК / ЛОГ
# ════════════════════════════════════════════════════════════════════════════

@dp.message(F.text == "📤 Передать кошелёк")
async def log_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📤 <b>Передача лога (TRC20)</b>\n\nВведите адрес кошелька:\n▪️ TRC20 — начинается с <b>T</b>, 34 символа",
        parse_mode="HTML", reply_markup=kb_cancel(),
    )
    await state.set_state(LogFSM.wallet)

@dp.message(LogFSM.wallet, F.text == "❌ Отмена")
async def log_c1(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.wallet)
async def log_wallet(message: Message, state: FSMContext):
    wallet = message.text.strip()
    if not is_trc20(wallet):
        await message.answer("❌ Неверный формат. Только TRC20 (начинается с T, 34 символа). Попробуйте снова:", parse_mode="HTML"); return
    await state.update_data(wallet=wallet)
    await message.answer("Введите сферу сделки:"); await state.set_state(LogFSM.deal_scope)

@dp.message(LogFSM.deal_scope, F.text == "❌ Отмена")
async def log_c2(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.deal_scope)
async def log_scope(message: Message, state: FSMContext):
    await state.update_data(deal_scope=message.text.strip())
    await message.answer("Введите сумму сделки (в USDT):"); await state.set_state(LogFSM.deal_amount)

@dp.message(LogFSM.deal_amount, F.text == "❌ Отмена")
async def log_c3(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.deal_amount)
async def log_amount(message: Message, state: FSMContext):
    await state.update_data(deal_amount=message.text.strip())
    await message.answer("Введите баланс кошелька:"); await state.set_state(LogFSM.wallet_balance)

@dp.message(LogFSM.wallet_balance, F.text == "❌ Отмена")
async def log_c4(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.wallet_balance)
async def log_balance(message: Message, state: FSMContext):
    await state.update_data(wallet_balance=message.text.strip())
    await message.answer("Выберите тип кошелька:", reply_markup=kb_wallet_type()); await state.set_state(LogFSM.wallet_type)

@dp.callback_query(LogFSM.wallet_type, F.data.startswith("wtype_"))
async def log_wtype(call: CallbackQuery, state: FSMContext):
    await state.update_data(wallet_type="Личный" if call.data == "wtype_personal" else "Биржа")
    await call.message.answer("Укажите от чьего лица вы общаетесь:", reply_markup=kb_gender())
    await call.answer(); await state.set_state(LogFSM.gender)

@dp.callback_query(LogFSM.gender, F.data.startswith("gender_"))
async def log_gender(call: CallbackQuery, state: FSMContext):
    await state.update_data(gender="Мужчина" if call.data == "gender_male" else "Женщина")
    await call.message.answer("Введите язык общения с клиентом:\n<i>Например: Русский, Английский</i>", parse_mode="HTML", reply_markup=kb_cancel())
    await call.answer(); await state.set_state(LogFSM.language)

@dp.message(LogFSM.language, F.text == "❌ Отмена")
async def log_c5(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.language)
async def log_lang(message: Message, state: FSMContext):
    await state.update_data(language=message.text.strip())
    await message.answer("Введите страну клиента:\n<i>Например: Germany, США</i>", parse_mode="HTML"); await state.set_state(LogFSM.country)

@dp.message(LogFSM.country, F.text == "❌ Отмена")
async def log_c6(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.country)
async def log_country(message: Message, state: FSMContext):
    await state.update_data(country=message.text.strip())
    await message.answer("Введите ваш номер или логин Instagram:\n<i>Пример: +48123123123 или @instagram</i>", parse_mode="HTML"); await state.set_state(LogFSM.contact)

@dp.message(LogFSM.contact, F.text == "❌ Отмена")
async def log_c7(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.contact)
async def log_contact(message: Message, state: FSMContext):
    await state.update_data(contact=message.text.strip())
    await message.answer("Выберите мессенджер клиента:", reply_markup=kb_messenger()); await state.set_state(LogFSM.messenger)

@dp.callback_query(LogFSM.messenger, F.data.startswith("msg_"))
async def log_msg(call: CallbackQuery, state: FSMContext):
    msg_map = {"msg_telegram": "Telegram", "msg_whatsapp": "WhatsApp", "msg_instagram": "Instagram"}
    messenger = msg_map[call.data]
    await state.update_data(messenger=messenger)
    await call.answer()
    await call.message.answer("Введите номер клиента:" if messenger == "WhatsApp" else "Введите username клиента (без @):", reply_markup=kb_cancel())
    await state.set_state(LogFSM.client_contact)

@dp.message(LogFSM.client_contact, F.text == "❌ Отмена")
async def log_c8(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.client_contact)
async def log_client(message: Message, state: FSMContext):
    await state.update_data(client_contact=message.text.strip())
    await message.answer("📝 Есть ли дополнительная информация по логу?", reply_markup=kb_extra_yn()); await state.set_state(LogFSM.extra_yn)

@dp.callback_query(LogFSM.extra_yn, F.data == "extra_yes")
async def log_extra_yes(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📝 Введите дополнительную информацию:", reply_markup=kb_cancel())
    await call.answer(); await state.set_state(LogFSM.extra_info)

@dp.callback_query(LogFSM.extra_yn, F.data == "extra_no")
async def log_extra_no(call: CallbackQuery, state: FSMContext):
    await state.update_data(extra_info=""); await call.answer()
    await finish_log(call.message, state, call.from_user)

@dp.message(LogFSM.extra_info, F.text == "❌ Отмена")
async def log_c9(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(LogFSM.extra_info)
async def log_extra(message: Message, state: FSMContext):
    await state.update_data(extra_info=message.text.strip())
    await finish_log(message, state, message.from_user)


async def finish_log(message, state: FSMContext, from_user):
    data = await state.get_data()
    await state.clear()
    user = await db.get_user(from_user.id)
    data["user_id"] = from_user.id
    data["user_tag"] = user["tag"] if user else str(from_user.id)
    log_number = await db.save_log(data)

    await message.answer(
        "✅ <b>Лог успешно сохранён и отправлен администраторам.</b>\n\n🕐 Среднее время взятия лога в работу сегодня: ~1 мин.",
        parse_mode="HTML", reply_markup=main_menu(),
    )

    extra = f"\n📝 Доп. инфо: <b>{data['extra_info']}</b>" if data.get("extra_info") else ""
    tag = f"@{from_user.username}" if from_user.username else f"<a href='tg://user?id={from_user.id}'>{from_user.full_name}</a>"
    admin_text = (
        f"📋 <b>Новый лог #{log_number}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👤 Воркер: {tag} | <b>{data['user_tag']}</b>\n"
        f"🆔 ID: <code>{from_user.id}</code>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💼 Кошелёк: <code>{data['wallet']}</code>\n"
        f"🔖 Тип: <b>{data['wallet_type']}</b> | 💰 Баланс: <b>{data['wallet_balance']} USDT</b>\n"
        f"📦 Сфера: <b>{data['deal_scope']}</b> | 💵 Сумма: <b>{data['deal_amount']} USDT</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🧍 От лица: <b>{data['gender']}</b> | 🌐 Язык: <b>{data['language']}</b>\n"
        f"🌍 Страна: <b>{data['country']}</b>\n"
        f"📞 Контакт воркера: <b>{data['contact']}</b>\n"
        f"📱 {data['messenger']}: <b>{data['client_contact']}</b>"
        f"{extra}"
    )
    for chat_id in [ADMIN_CHAT_ID, SUPPORT_CHAT_ID]:
        try:
            await bot.send_message(chat_id, admin_text, reply_markup=kb_log_admin(log_number), parse_mode="HTML")
        except Exception as e:
            logging.error(f"Log send error to {chat_id}: {e}")


# ─── Лог: взять / не брать ────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("log_take:"))
async def log_take(call: CallbackQuery):
    log_number = call.data.split(":")[1]
    log = await db.get_log(log_number)
    if not log:
        await call.answer("Лог не найден.", show_alert=True); return
    if log["status"] != "pending":
        who = f"@{log['support_username']}" if log.get("support_username") else "другой саппорт"
        await call.answer(f"Лог уже взят — {who}", show_alert=True); return
    sup = call.from_user.username or str(call.from_user.id)
    await db.take_log(log_number, call.from_user.id, sup)
    try:
        await bot.send_message(log["user_id"], f"🔔 <b>Ваш лог #{log_number} принят в обработку.</b>\n\nСаппорт: @{sup}\nСтатус: <b>В обработке</b>", parse_mode="HTML")
    except Exception: pass
    try:
        await call.message.edit_reply_markup(reply_markup=kb_log_result(log_number))
    except Exception: pass
    await call.answer(f"Лог #{log_number} взят! (@{sup})", show_alert=True)

@dp.callback_query(F.data.startswith("log_skip:"))
async def log_skip(call: CallbackQuery, state: FSMContext):
    log_number = call.data.split(":")[1]
    log = await db.get_log(log_number)
    if log and log["status"] != "pending":
        who = f"@{log['support_username']}" if log.get("support_username") else "другой саппорт"
        await call.answer(f"Лог уже взят — {who}", show_alert=True); return
    await state.update_data(skip_log=log_number)
    await call.message.answer("Укажите причину или /skip:", reply_markup=kb_cancel())
    await call.answer(); await state.set_state(RejectLog.reason)

@dp.message(RejectLog.reason, F.text == "❌ Отмена")
async def rej_cancel(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(RejectLog.reason, Command("skip"))
async def rej_skip(message: Message, state: FSMContext):
    data = await state.get_data()
    log_number = data.get("skip_log")
    await state.clear()
    await message.answer("Пропущено.", reply_markup=main_menu())
    if log_number:
        log = await db.get_log(log_number)
        if log:
            sup = message.from_user.username or str(message.from_user.id)
            try:
                await bot.send_message(
                    log["user_id"],
                    f"❌ <b>Саппорт отказался от вашего лога #{log_number}.</b>\n\nСаппорт: @{sup}\nПричина: не указана\n\nПопробуйте отправить лог позже.",
                    parse_mode="HTML",
                )
            except Exception: pass

@dp.message(RejectLog.reason)
async def rej_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    log_number = data.get("skip_log")
    reason = message.text.strip()
    await state.clear()
    await message.answer("✅ Причина записана.", reply_markup=main_menu())
    if log_number:
        log = await db.get_log(log_number)
        if log:
            sup = message.from_user.username or str(message.from_user.id)
            try:
                await bot.send_message(
                    log["user_id"],
                    f"❌ <b>Саппорт отказался от вашего лога #{log_number}.</b>\n\nСаппорт: @{sup}\nПричина: {reason}\n\nПопробуйте отправить лог позже.",
                    parse_mode="HTML",
                )
            except Exception: pass


# ─── Лог: результат ──────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("log_success:"))
async def log_success(call: CallbackQuery):
    log_number = call.data.split(":")[1]
    log = await db.get_log(log_number)
    if not log:
        await call.answer("Лог не найден.", show_alert=True); return
    if log["status"] in ("success", "fail", "invalid"):
        await call.answer(f"Лог уже обработан: {log['status']}", show_alert=True); return
    await db.set_log_result(log_number, "success")
    try:
        await bot.send_message(log["user_id"], f"✅ <b>Лог #{log_number} — Успешный!</b>", parse_mode="HTML")
    except Exception as e:
        logging.error(f"log_success: {e}")
    try:
        await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Успешный", callback_data="done")]]))
    except Exception: pass
    await call.answer("Успешный.", show_alert=True)

@dp.callback_query(F.data.startswith("log_fail:"))
async def log_fail(call: CallbackQuery):
    log_number = call.data.split(":")[1]
    log = await db.get_log(log_number)
    if not log:
        await call.answer("Лог не найден.", show_alert=True); return
    if log["status"] in ("success", "fail", "invalid"):
        await call.answer(f"Лог уже обработан: {log['status']}", show_alert=True); return
    await db.set_log_result(log_number, "fail")
    try:
        await bot.send_message(log["user_id"], f"❌ <b>Лог #{log_number} — Неуспешный.</b>", parse_mode="HTML")
    except Exception as e:
        logging.error(f"log_fail: {e}")
    try:
        await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Неуспешный", callback_data="done")]]))
    except Exception: pass
    await call.answer("Неуспешный.", show_alert=True)

@dp.callback_query(F.data.startswith("log_invalid:"))
async def log_invalid(call: CallbackQuery):
    log_number = call.data.split(":")[1]
    log = await db.get_log(log_number)
    if not log:
        await call.answer("Лог не найден.", show_alert=True); return
    if log["status"] in ("success", "fail", "invalid"):
        await call.answer(f"Лог уже обработан: {log['status']}", show_alert=True); return
    await db.set_log_result(log_number, "invalid")
    try:
        await bot.send_message(log["user_id"], f"🚫 <b>Лог #{log_number} — Не валидный.</b>", parse_mode="HTML")
    except Exception as e:
        logging.error(f"log_invalid: {e}")
    try:
        await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚫 Не валидный", callback_data="done")]]))
    except Exception: pass
    await call.answer("Не валидный.", show_alert=True)


# ─── Полезная информация ──────────────────────────────────────────────────────

@dp.message(F.text == "💡 Полезная информация")
async def useful_info(message: Message):
    await message.answer("💡 <b>Полезная информация</b>\n\nВыберите нужный раздел:", parse_mode="HTML", reply_markup=kb_useful_info())

@dp.callback_query(F.data == "info_manuals")
async def info_manuals(call: CallbackQuery): await send_invite(call, -1003915324407, "Мануалы")

@dp.callback_query(F.data == "info_payouts")
async def info_payouts(call: CallbackQuery): await send_invite(call, PAYOUTS_CHANNEL, "Выплаты")

@dp.callback_query(F.data == "info_support")
async def info_support(call: CallbackQuery):
    await call.message.answer("🛠 <b>Техническая поддержка:</b>\n\nt.me/black_crypto_c", parse_mode="HTML"); await call.answer()

@dp.callback_query(F.data == "info_channel")
async def info_channel(call: CallbackQuery): await send_invite(call, -1003902417569, "Полезная информация")

@dp.callback_query(F.data == "info_docs")
async def info_docs(call: CallbackQuery): await send_invite(call, -1003959276802, "Документы")

@dp.callback_query(F.data == "info_tools")
async def info_tools(call: CallbackQuery):
    await call.message.answer("🔧 <b>Инструменты</b>", parse_mode="HTML", reply_markup=kb_tools()); await call.answer()

@dp.callback_query(F.data == "tools_back")
async def tools_back(call: CallbackQuery):
    await call.message.answer("💡 <b>Полезная информация</b>\n\nВыберите нужный раздел:", parse_mode="HTML", reply_markup=kb_useful_info()); await call.answer()

@dp.callback_query(F.data == "tool_phone")
async def tool_phone(call: CallbackQuery, state: FSMContext):
    await call.message.answer(
        "📱 <b>Введите номер телефона</b>\n\nФормат:\n<code>+921111999922</code> или <code>9228888231</code>\n\n<i>Указывайте с кодом страны.</i>",
        parse_mode="HTML",
    )
    await call.answer(); await state.set_state(CheckPhone.waiting)

@dp.message(CheckPhone.waiting)
async def tool_phone_process(message: Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "").replace("-", "")
    clean = phone.lstrip("+")
    await state.clear()
    await message.answer(
        f"📱 <b>Номер:</b> <code>{phone}</code>\n\n"
        f"▶️ <a href='https://wa.me/{clean}'>Написать в WhatsApp</a>\n"
        f"▶️ <a href='https://t.me/+{clean}'>Ссылка на Telegram</a>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Проверить ещё", callback_data="tool_phone")],
            [InlineKeyboardButton(text="◀️ В меню", callback_data="tools_back")],
        ]),
    )

@dp.message(F.text == "📡 Резервный канал")
async def reserve_ch(message: Message):
    await message.answer(f"📡 <b>Резервный канал:</b>\n{RESERVE_CHANNEL}", parse_mode="HTML")


# ════════════════════════════════════════════════════════════════════════════
# АДМИН КОМАНДЫ
# ════════════════════════════════════════════════════════════════════════════

@dp.message(Command("mystats"))
async def cmd_mystats(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Вы не зарегистрированы в боте."); return
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1", message.from_user.id)
        success = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1 AND status='success'", message.from_user.id)
        fail = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1 AND status='fail'", message.from_user.id)
        invalid = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1 AND status='invalid'", message.from_user.id)
    counted = (success or 0) + (fail or 0)
    success_pct = round((success or 0) / counted * 100, 1) if counted > 0 else 0
    text = (
        f"📊 <b>Ваша статистика</b> — <b>{user['tag']}</b>\n\n"
        f"📋 Логов всего: <b>{total or 0}</b>\n"
        f"✅ Успешных: <b>{success or 0}</b>\n"
        f"❌ Неуспешных: <b>{fail or 0}</b>\n"
        f"🚫 Не валидных: <b>{invalid or 0}</b>\n"
        f"📈 Процент успеха: <b>{success_pct}%</b>\n\n"
        f"💰 Сумма выплат: <b>{user['payout_sum']:.2f} USDT</b>\n"
        f"🧾 Кол-во выплат: <b>{user['payout_count']}</b>"
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("userinfo"))
async def admin_userinfo(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /userinfo тег"); return
    tag = args[1].lstrip("@")
    user = await db.get_user_by_tag(tag)
    if not user:
        await message.answer("❌ Пользователь не найден."); return
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1", user["user_id"])
        success = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1 AND status='success'", user["user_id"])
        fail = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1 AND status='fail'", user["user_id"])
        invalid = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1 AND status='invalid'", user["user_id"])
        pending = await conn.fetchval("SELECT COUNT(*) FROM user_logs WHERE user_id=$1 AND status='pending'", user["user_id"])
    counted = (success or 0) + (fail or 0)
    success_pct = round((success or 0) / counted * 100, 1) if counted > 0 else 0
    banned = await db.is_banned(user["user_id"])
    mentor_str = "❌"
    if user.get("mentor_id"):
        mentor = await db.get_mentor(user["mentor_id"])
        if mentor:
            left = user.get("mentor_payouts_left", 0)
            mentor_str = f"@{mentor['username']} (осталось: {left})"
    username_str = f"@{user['username']}" if user.get("username") else "—"
    text = (
        f"👤 <b>Информация о пользователе</b>\n\n"
        f"⭐️ Тег: <b>{user['tag']}</b>\n"
        f"🔗 Username: {username_str}\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"📅 В команде с: <b>{user.get('joined_at', '—')}</b>\n"
        f"🚫 Заблокирован: <b>{'Да' if banned else 'Нет'}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📋 Логов всего: <b>{total or 0}</b>\n"
        f"✅ Успешных: <b>{success or 0}</b>\n"
        f"❌ Неуспешных: <b>{fail or 0}</b>\n"
        f"🚫 Не валидных: <b>{invalid or 0}</b>\n"
        f"⏳ На рассмотрении: <b>{pending or 0}</b>\n"
        f"📈 Процент успеха: <b>{success_pct}%</b>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💰 Сумма выплат: <b>{user['payout_sum']:.2f} USDT</b>\n"
        f"🧾 Кол-во выплат: <b>{user['payout_count']}</b>\n"
        f"📊 Процент выплат: <b>{int(user['payout_pct'])}%</b>\n"
        f"🤝 Наставник: <b>{mentor_str}</b>"
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("work"))
async def admin_work(message: Message):
    if not is_admin(message.from_user.id): return
    await db.set_setting("work_mode", "Дневной ворк")
    text = "START WORK 🟢\n\nВсем заряду и побольше клиентов!"
    for chat_id in [ADMIN_CHAT_ID, SUPPORT_CHAT_ID, WORKERS_CHAT_ID]:
        try: await bot.send_message(chat_id, text)
        except Exception: pass
    await message.answer(f"✅ {text}")


@dp.message(Command("stopwork"))
async def admin_stopwork(message: Message):
    if not is_admin(message.from_user.id): return
    await db.set_setting("work_mode", "Стоп ворк")
    text = "STOP WORK 🔴\n\nКоманда остановила работу. Логи не принимаются."
    for chat_id in [ADMIN_CHAT_ID, SUPPORT_CHAT_ID, WORKERS_CHAT_ID]:
        try: await bot.send_message(chat_id, text)
        except Exception: pass
    await message.answer(f"✅ {text}")


@dp.message(Command("adminhelp"))
async def admin_help(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer(
        "📋 <b>Все админские команды:</b>\n\n"
        "━━ Управление ━━\n"
        "/setmode день|ночь|стоп\n"
        "/setpct 70 — процент всем\n"
        "/setpct тег 70 — конкретному\n"
        "/pay тег 500 — выплата\n"
        "/delpay тег 500 — удалить выплату\n"
        "/setcash 1234 — касса\n\n"
        "━━ Пользователи ━━\n"
        "/ban тег [причина]\n"
        "/unban тег\n\n"
        "━━ Саппорты ━━\n"
        "/addsupport @username\n"
        "/delsupport @username\n\n"
        "━━ Наставники ━━\n"
        "/addmentor тег @username процент [описание]\n"
        "/delmentor тег — снять с ученика\n"
        "/delmentorglobal тег — удалить из команды\n"
        "/setmentorfee тег процент\n"
        "/setmentorbio тег текст\n\n"
        "━━ Роли (инструктаж) ━━\n"
        "/setrole creator|moderator|developer @username\n"
        "/setmentors @user1 @user2\n\n"
        "━━ Рассылка ━━\n"
        "/broadcast\n"
        "\n━━ Чеки ━━\n"
        "/setdomain https://example.com — домен для чеков\n"
        "/invoices — последние 20 чеков\n",
        parse_mode="HTML",
    )

@dp.message(Command("setmode"))
async def admin_setmode(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /setmode день|ночь|стоп"); return
    mode_map = {"день": "Дневной ворк", "ночь": "Ночной ворк", "стоп": "Стоп ворк"}
    mode = mode_map.get(args[1].lower().strip())
    if not mode:
        await message.answer("Варианты: день | ночь | стоп"); return
    await db.set_setting("work_mode", mode)
    await message.answer(f"✅ Режим: <b>{mode}</b>", parse_mode="HTML")

@dp.message(Command("setpct"))
async def admin_setpct(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) == 2:
        try:
            pct = float(args[1]); await db.set_all_pct(pct)
            await message.answer(f"✅ Процент для всех: <b>{pct}%</b>", parse_mode="HTML")
        except ValueError: await message.answer("Использование: /setpct 70")
    elif len(args) == 3:
        tag = args[1].lstrip("@")
        try:
            pct = float(args[2]); user = await db.get_user_by_tag(tag)
            if not user:
                await message.answer("❌ Не найден."); return
            await db.set_user_pct(user["user_id"], pct)
            await message.answer(f"✅ Процент для <b>{tag}</b>: <b>{pct}%</b>", parse_mode="HTML")
        except ValueError: await message.answer("Использование: /setpct тег 70")
    else:
        await message.answer("Использование:\n/setpct 70 — всем\n/setpct тег 70 — конкретному")

@dp.message(Command("pay"))
async def admin_pay(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /pay тег 500"); return
    tag = args[1].lstrip("@")
    try: amount = float(args[2])
    except ValueError:
        await message.answer("Сумма — число."); return
    user = await db.get_user_by_tag(tag)
    if not user:
        await message.answer("❌ Не найден."); return
    pct = user["payout_pct"]
    worker_share = round(amount * pct / 100, 2)
    mentor_info = await db.add_payout(user["user_id"], amount)

    # Сообщение воркеру
    mentor_line = ""
    if mentor_info.get("mentor_id"):
        mentor_line = f"\n💼 Доля наставника ({mentor_info['fee_pct']}%): <b>{fmt(mentor_info['mentor_fee'])} USDT</b>"
        if mentor_info.get("mentor_removed"):
            mentor_line += "\n\n⚠️ Наставник снят (5 выплат завершено)"

    worker_text = f"💸 <b>Выплата получена!</b>\n\n💰 Сумма: <b>{fmt(amount)} USDT</b>\n📊 Ваш процент: <b>{int(pct)}%</b>\n✅ Ваша доля: <b>{fmt(worker_share)} USDT</b>{mentor_line}"
    try:
        from aiogram.types import FSInputFile
        photo = FSInputFile("newpayment.png")
        await bot.send_photo(user["user_id"], photo=photo, caption=worker_text, parse_mode="HTML")
    except Exception:
        await bot.send_message(user["user_id"], worker_text, parse_mode="HTML")

    # Уведомление наставнику
    if mentor_info.get("mentor_id"):
        try:
            removed_text = "\n\n✅ Обучение завершено — ученик снят." if mentor_info.get("mentor_removed") else ""
            await bot.send_message(
                mentor_info["mentor_id"],
                f"💰 <b>Вам начислена доля от выплаты!</b>\n\nУченик: <b>{tag}</b>\nВаш процент: <b>{mentor_info['fee_pct']}%</b>\nВаша доля: <b>{fmt(mentor_info['mentor_fee'])} USDT</b>{removed_text}",
                parse_mode="HTML",
            )
        except Exception: pass

    # В канал выплат
    mentor_channel_line = f"\n👨‍🏫 Доля наставника @{mentor_info['mentor_username']} ({mentor_info['fee_pct']}%): <b>{fmt(mentor_info['mentor_fee'])} USDT</b>" if mentor_info.get("mentor_id") else ""
    payout_text = f"💳 <b>Новая оплата</b>\n\n👤 Тег: <b>{tag}</b>\n💰 Сумма: <b>{fmt(amount)} USDT</b>\n📊 Доля воркера ({int(pct)}%): <b>{fmt(worker_share)} USDT</b>{mentor_channel_line}"
    try:
        from aiogram.types import FSInputFile
        photo = FSInputFile("newpayment.png")
        sent = await bot.send_photo(PAYOUTS_CHANNEL, photo=photo, caption=payout_text, parse_mode="HTML")
    except Exception:
        sent = await bot.send_message(PAYOUTS_CHANNEL, payout_text, parse_mode="HTML")
    # Дублируем в чат воркеров
    try:
        await bot.forward_message(WORKERS_CHAT_ID, PAYOUTS_CHANNEL, sent.message_id)
    except Exception:
        try:
            await bot.send_message(WORKERS_CHAT_ID, payout_text, parse_mode="HTML")
        except Exception: pass
    await message.answer(f"✅ <b>{fmt(amount)} USDT</b> начислено <b>{tag}</b>", parse_mode="HTML")

@dp.message(Command("delpay"))
async def admin_delpay(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /delpay тег 500"); return
    tag = args[1].lstrip("@")
    try: amount = float(args[2])
    except ValueError:
        await message.answer("Сумма — число."); return
    user = await db.get_user_by_tag(tag)
    if not user:
        await message.answer("❌ Не найден."); return
    await db.del_payout(user["user_id"], amount)
    await message.answer(f"✅ У <b>{tag}</b> удалена выплата на <b>{fmt(amount)} USDT</b>.", parse_mode="HTML")
    try:
        await bot.send_message(user["user_id"], f"⚠️ <b>Выплата на {fmt(amount)} USDT удалена администратором.</b>", parse_mode="HTML")
    except Exception: pass

@dp.message(Command("setcash"))
async def admin_setcash(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /setcash 1234.56"); return
    try:
        val = float(args[1]); await db.set_setting("project_cash", str(val))
        await message.answer(f"✅ Касса: <b>{val} USDT</b>", parse_mode="HTML")
    except ValueError: await message.answer("Сумма — число.")

@dp.message(Command("addsupport"))
async def admin_addsupport(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /addsupport @username"); return
    username = args[1].lstrip("@")
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM users WHERE username=$1", username)
    if not row:
        await message.answer("❌ Не найден."); return
    await db.add_support(row["user_id"], username)
    await message.answer(f"✅ @{username} добавлен как саппорт.")

@dp.message(Command("delsupport"))
async def admin_delsupport(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /delsupport @username"); return
    username = args[1].lstrip("@")
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM supports WHERE username=$1", username)
    if not row:
        await message.answer("❌ Саппорт не найден."); return
    await db.del_support(row["user_id"])
    await message.answer(f"✅ @{username} удалён из саппортов.")

# /addmentor тег @username процент [описание]
@dp.message(Command("addmentor"))
async def admin_addmentor(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=4)
    if len(args) < 4:
        await message.answer("Использование: /addmentor тег @username процент [описание]"); return
    tag = args[1].lstrip("@")
    username = args[2].lstrip("@")
    try: fee_pct = float(args[3])
    except ValueError:
        await message.answer("Процент — число."); return
    bio = args[4] if len(args) > 4 else ""
    user = await db.get_user_by_tag(tag)
    if not user:
        await message.answer("❌ Пользователь не найден."); return
    await db.add_mentor(user["user_id"], username, tag, fee_pct, bio)
    await message.answer(f"✅ <b>{tag}</b> (@{username}) добавлен как наставник с комиссией {fee_pct}%.", parse_mode="HTML")

@dp.message(Command("delmentor"))
async def admin_delmentor(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /delmentor тег_ученика"); return
    worker = await db.get_user_by_tag(args[1].lstrip("@"))
    if not worker:
        await message.answer("❌ Воркер не найден."); return
    await db.remove_mentor_from_user(worker["user_id"])
    await message.answer(f"✅ Наставник снят с <b>{worker['tag']}</b>.", parse_mode="HTML")
    try:
        await bot.send_message(worker["user_id"], "ℹ️ Администратор снял вашего наставника.", parse_mode="HTML")
    except Exception: pass

@dp.message(Command("delmentorglobal"))
async def admin_delmentorglobal(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /delmentorglobal тег_наставника"); return
    mentor = await db.get_mentor_by_tag(args[1].lstrip("@"))
    if not mentor:
        await message.answer("❌ Наставник не найден."); return
    await db.del_mentor_global(mentor["user_id"])
    await message.answer(f"✅ Наставник <b>{args[1]}</b> удалён из команды.", parse_mode="HTML")

@dp.message(Command("setmentorfee"))
async def admin_setmentorfee(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /setmentorfee тег процент"); return
    mentor = await db.get_mentor_by_tag(args[1].lstrip("@"))
    if not mentor:
        await message.answer("❌ Наставник не найден."); return
    try: fee = float(args[2])
    except ValueError:
        await message.answer("Процент — число."); return
    await db.set_mentor_fee(mentor["user_id"], fee)
    await message.answer(f"✅ Комиссия наставника <b>{args[1]}</b> установлена: <b>{fee}%</b>", parse_mode="HTML")

@dp.message(Command("setmentorbio"))
async def admin_setmentorbio(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /setmentorbio тег текст описания"); return
    mentor = await db.get_mentor_by_tag(args[1].lstrip("@"))
    if not mentor:
        await message.answer("❌ Наставник не найден."); return
    await db.set_mentor_bio(mentor["user_id"], args[2])
    await message.answer(f"✅ Описание наставника обновлено.")

@dp.message(Command("ban"))
async def admin_ban(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("Использование: /ban тег [причина]"); return
    tag = args[1].lstrip("@"); reason = args[2] if len(args) > 2 else ""
    user = await db.get_user_by_tag(tag)
    if not user:
        await message.answer("❌ Не найден."); return
    await db.ban_user(user["user_id"], reason)
    reason_text = f"\nПричина: {reason}" if reason else ""
    await message.answer(f"✅ <b>{tag}</b> заблокирован.{reason_text}", parse_mode="HTML")
    try: await bot.send_message(user["user_id"], f"🚫 <b>Вы заблокированы.</b>{reason_text}", parse_mode="HTML")
    except Exception: pass

@dp.message(Command("unban"))
async def admin_unban(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /unban тег"); return
    user = await db.get_user_by_tag(args[1].lstrip("@"))
    if not user:
        await message.answer("❌ Не найден."); return
    await db.unban_user(user["user_id"])
    await message.answer(f"✅ <b>{args[1]}</b> разблокирован.", parse_mode="HTML")
    try: await bot.send_message(user["user_id"], "✅ <b>Блокировка снята.</b>", parse_mode="HTML")
    except Exception: pass

@dp.message(Command("setrole"))
async def admin_setrole(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /setrole creator|moderator|developer @username"); return
    role_map = {"creator": "role_creator", "moderator": "role_moderator", "developer": "role_developer"}
    if args[1].lower() not in role_map:
        await message.answer("Роли: creator, moderator, developer"); return
    await db.set_setting(role_map[args[1].lower()], f"@{args[2].lstrip('@')}")
    await message.answer(f"✅ {args[1]} = @{args[2].lstrip('@')}")

@dp.message(Command("setmentors"))
async def admin_setmentors(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()[1:]
    if not args:
        await message.answer("Использование: /setmentors @user1 @user2"); return
    mentors = " ".join([f"@{a.lstrip('@')}" for a in args])
    await db.set_setting("role_mentors", mentors)
    await message.answer(f"✅ Наставники в инструктаже: {mentors}")

@dp.message(Command("addadmin"))
async def admin_addadmin(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /addadmin user_id"); return
    try:
        new_admin_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом."); return
    admins = await db.get_setting("extra_admins")
    ids = [int(x) for x in admins.split(",") if x.strip().isdigit()] if admins else []
    if new_admin_id not in ids:
        ids.append(new_admin_id)
        await db.set_setting("extra_admins", ",".join(str(i) for i in ids))
    ADMIN_IDS.append(new_admin_id)
    await message.answer(f"✅ Пользователь <code>{new_admin_id}</code> добавлен как администратор.", parse_mode="HTML")
    try: await bot.send_message(new_admin_id, "✅ <b>Вам выданы права администратора.</b>", parse_mode="HTML")
    except Exception: pass

@dp.message(Command("deladmin"))
async def admin_deladmin(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /deladmin user_id"); return
    try:
        del_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом."); return
    if del_id in ADMIN_IDS:
        ADMIN_IDS.remove(del_id)
    admins = await db.get_setting("extra_admins")
    ids = [int(x) for x in admins.split(",") if x.strip().isdigit()] if admins else []
    if del_id in ids:
        ids.remove(del_id)
        await db.set_setting("extra_admins", ",".join(str(i) for i in ids))
    await message.answer(f"✅ Пользователь <code>{del_id}</code> удалён из администраторов.", parse_mode="HTML")


@dp.message(Command("broadcast"))
async def admin_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await message.answer("📢 Введите текст рассылки. Для отмены: /cancel")
    await state.set_state(Broadcast.waiting)

@dp.message(Broadcast.waiting, Command("cancel"))
async def broadcast_cancel(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.")

@dp.message(Broadcast.waiting)
async def broadcast_send(message: Message, state: FSMContext):
    await state.clear()
    users = await db.get_all_users()
    sent = 0; failed = 0
    await message.answer(f"📢 Рассылка для {len(users)} пользователей...")
    for uid in users:
        try:
            await bot.send_message(uid, message.text, parse_mode="HTML"); sent += 1
            await asyncio.sleep(0.05)
        except Exception: failed += 1
    await message.answer(f"✅ Готово.\n📨 Отправлено: {sent}\n❌ Не доставлено: {failed}")


# ── Саппорт ───────────────────────────────────────────────────────────────────

@dp.message(Command("onshift"))
async def support_onshift(message: Message):
    if not await db.is_support(message.from_user.id): return
    await db.set_support_shift(message.from_user.id, True)
    await message.answer("✅ Вы вышли на смену.")

@dp.message(Command("offshift"))
async def support_offshift(message: Message):
    if not await db.is_support(message.from_user.id): return
    await db.set_support_shift(message.from_user.id, False)
    await message.answer("✅ Вы ушли со смены.")

@dp.callback_query(F.data == "done")
async def cb_done(call: CallbackQuery): await call.answer()


# ════════════════════════════════════════════════════════════════════════════
# ИНВОЙСЫ / ЧЕКИ
# ════════════════════════════════════════════════════════════════════════════

@dp.message(F.text == "🧾 Создать чек")
async def invoice_start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    if not await db.is_approved(message.from_user.id):
        await message.answer("🚫 Доступ закрыт."); return
    await message.answer(
        "🧾 <b>Создание чека</b>\n\n"
        "Введите сумму в USDT:\n"
        "<i>Например: 50 или 150.50</i>",
        parse_mode="HTML",
        reply_markup=kb_cancel(),
    )
    await state.set_state(InvoiceFSM.amount)


@dp.message(InvoiceFSM.amount, F.text == "❌ Отмена")
async def invoice_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu())


@dp.message(InvoiceFSM.amount)
async def invoice_process(message: Message, state: FSMContext):
    raw = message.text.strip().replace(",", ".")
    try:
        amount = float(raw)
        if amount <= 0 or amount > 1_000_000:
            raise ValueError
        amount = round(amount, 2)
    except ValueError:
        await message.answer("❌ Неверная сумма. Введите число больше 0:\n<i>Например: 50 или 150.50</i>", parse_mode="HTML")
        return

    await state.clear()

    user = await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name,
    )

    token = await db.create_invoice(message.from_user.id, user["tag"], amount)
    domain = await db.get_setting("invoice_domain") or "https://example.com"
    link = f"{domain.rstrip('/')}/?t={token}"

    await message.answer(
        f"✅ <b>Чек создан!</b>\n\n"
        f"💰 Сумма: <b>{amount:.2f} USDT</b>\n"
        f"🔑 Токен: <code>{token}</code>\n\n"
        f"🔗 Ссылка:\n{link}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Мои чеки", callback_data="my_invoices:0")],
        ]),
    )


@dp.callback_query(F.data.startswith("my_invoices:"))
async def my_invoices_cb(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    invoices = await db.get_user_invoices(call.from_user.id, limit=50)
    if not invoices:
        await call.answer("У вас нет чеков.", show_alert=True); return

    per_page = 5
    total = len(invoices)
    start = page * per_page
    chunk = invoices[start:start + per_page]

    status_icons = {"pending": "⏳", "paid": "✅", "expired": "❌"}
    lines = [f"🧾 <b>Ваши чеки</b> (всего: {total})\n"]
    for inv in chunk:
        icon = status_icons.get(inv["status"], "▪️")
        lines.append(f"{icon} <code>{inv['token']}</code> — <b>{inv['amount']:.2f} USDT</b> | {inv['created_at']}")

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"my_invoices:{page-1}"))
    total_pages = max(1, (total + per_page - 1) // per_page)
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"my_invoices:{page+1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[nav] if nav else [])
    try:
        await call.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    except Exception:
        await call.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await call.answer()


@dp.message(Command("myinvoices"))
async def cmd_myinvoices(message: Message):
    invoices = await db.get_user_invoices(message.from_user.id, limit=10)
    if not invoices:
        await message.answer("📭 У вас нет чеков."); return
    domain = await db.get_setting("invoice_domain") or "https://example.com"
    status_icons = {"pending": "⏳", "paid": "✅", "expired": "❌"}
    lines = ["🧾 <b>Ваши последние чеки:</b>\n"]
    for inv in invoices:
        icon = status_icons.get(inv["status"], "▪️")
        link = f"{domain.rstrip('/')}/?t={inv['token']}"
        lines.append(f"{icon} <b>{inv['amount']:.2f} USDT</b> | <code>{inv['token']}</code>\n   🔗 {link}\n   📅 {inv['created_at']}\n")
    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


# ── Админ: управление доменом и просмотр всех чеков ──────────────────────────

@dp.message(Command("setdomain"))
async def admin_setdomain(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=1)
    if len(args) != 2:
        current = await db.get_setting("invoice_domain") or "не задан"
        await message.answer(
            f"🌐 <b>Управление доменом чеков</b>\n\n"
            f"Текущий домен: <code>{current}</code>\n\n"
            f"Использование: /setdomain https://example.com",
            parse_mode="HTML",
        )
        return
    domain = args[1].strip().rstrip("/")
    if not domain.startswith("http"):
        await message.answer("❌ Домен должен начинаться с http:// или https://"); return
    await db.set_setting("invoice_domain", domain)
    await message.answer(f"✅ Домен чеков установлен:\n<code>{domain}</code>", parse_mode="HTML")


@dp.message(Command("invoices"))
async def admin_invoices(message: Message):
    if not is_admin(message.from_user.id): return
    invoices = await db.get_all_invoices(limit=20)
    if not invoices:
        await message.answer("📭 Чеков нет."); return
    domain = await db.get_setting("invoice_domain") or "https://example.com"
    status_icons = {"pending": "⏳", "paid": "✅", "expired": "❌"}
    lines = [f"🧾 <b>Последние 20 чеков:</b>\n"]
    for inv in invoices:
        icon = status_icons.get(inv["status"], "▪️")
        lines.append(
            f"{icon} <b>{inv['user_tag']}</b> | <b>{inv['amount']:.2f} USDT</b>\n"
            f"   🔑 <code>{inv['token']}</code> | 📅 {inv['created_at']}\n"
        )
    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


# ─── Run ─────────────────────────────────────────────────────────────────────

async def main():
    await db.init_db()
    # Загружаем дополнительных админов из базы
    extra = await db.get_setting("extra_admins")
    if extra:
        for uid in extra.split(","):
            uid = uid.strip()
            if uid.isdigit():
                uid_int = int(uid)
                if uid_int not in ADMIN_IDS:
                    ADMIN_IDS.append(uid_int)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
