import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F, BaseMiddleware
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
    TelegramObject,
)
from typing import Any, Callable, Awaitable

from config import ADMIN_CHAT_ID, ADMIN_IDS, BOT_TOKEN, RESERVE_CHANNEL
import database as db
from url_builder import build_invoice_url, TEMPLATE_PRESETS, PRESET_LABELS
from onboarding import router as onboarding_router, start_onboarding

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(onboarding_router)

PAYOUTS_CHANNEL = -1003840310493
SUPPORT_CHAT_ID = -5285318192
WORKERS_CHAT_ID = -1003986458830


# ─── Ban middleware ───────────────────────────────────────────────────────────

class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]], event: TelegramObject, data: dict) -> Any:
        user = data.get("event_from_user")
        if user and await db.is_banned(user.id):
            return
        return await handler(event, data)

dp.message.middleware(BanMiddleware())
dp.callback_query.middleware(BanMiddleware())


# ─── FSM ─────────────────────────────────────────────────────────────────────

class ChangeTag(StatesGroup):
    waiting = State()

class CheckPhone(StatesGroup):
    waiting = State()

class Broadcast(StatesGroup):
    waiting = State()

class Leavementor(StatesGroup):
    reason = State()

class InvoiceFSM(StatesGroup):
    amount = State()
    from_name = State()      # для Coinbase: имя отправителя
    wallet_address = State() # для Coinbase: адрес получателя

class AddSiteFSM(StatesGroup):
    template = State()   # выбор шаблона через inline-кнопки
    name     = State()   # ввод названия
    domain   = State()   # ввод домена
    wallet   = State()   # ввод wallet_address (только для Coinbase)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def fmt(n): return f"{n:,.2f}".replace(",", " ")

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🧾 Создать чек"), KeyboardButton(text="📚 Пройти инструктаж")],
            [KeyboardButton(text="💡 Полезная информация"), KeyboardButton(text="📡 Резервный канал")],
            [KeyboardButton(text="🎓 Наставники")],
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
        f"🧾 Чеков создано: <b>{user.get('invoice_count', 0)}</b>\n\n"
        f"💰 Сумма выплат: <b>{user['payout_sum']} USDT</b>\n"
        f"🤝 Наставник: <b>{mentor_str}</b>\n"
        f"📊 Процент выплат: <b>{int(user['payout_pct'])}%</b>\n"
        f"🏦 Касса проекта: <b>{project_cash} USDT</b>\n\n"
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

def format_top_detailed(rows: list, title: str) -> str:
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    if not rows:
        return f"{title}\n\nПока нет данных."
    text = f"{title}\n━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(rows, 1):
        medal = medals.get(i, f"{i}.")
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
        await bot.send_message(mentor_id, f"🎓 <b>Новый ученик!</b>\n\nПользователь <b>{user['tag']}</b> выбрал вас наставником.", parse_mode="HTML")
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
        await message.answer("✅ <b>Вы уже прошли инструктаж.</b>", parse_mode="HTML"); return
    await start_onboarding(message, state)


# ─── Топ ─────────────────────────────────────────────────────────────────────

@dp.message(Command("top"))
async def cmd_top(message: Message):
    rows = await db.get_top_all()
    cash = await db.get_setting("project_cash")
    text = format_top_detailed(rows, "🏆 <b>Топ воркеров — Все время</b>")
    text += f"\n\n🏦 <b>Общая касса проекта: {cash} USDT</b>"
    await message.answer(text, parse_mode="HTML")


# ════════════════════════════════════════════════════════════════════════════
# СОЗДАНИЕ ЧЕКА
# ════════════════════════════════════════════════════════════════════════════

@dp.message(F.text == "🧾 Создать чек")
async def invoice_start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    if not await db.is_approved(message.from_user.id):
        await message.answer("🚫 Доступ закрыт."); return

    sites = await db.get_active_sites()
    if not sites:
        await message.answer("❌ <b>Нет доступных сайтов.</b>\n\nОбратитесь к администратору.", parse_mode="HTML"); return

    buttons = [[InlineKeyboardButton(text=s["name"], callback_data=f"site_pick:{s['id']}")] for s in sites]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="site_cancel")])
    from aiogram.types import FSInputFile
    try:
        photo = FSInputFile("choosesite.png")
        await message.answer_photo(
            photo=photo,
            caption="🌐 <b>Выберите сайт для создания чека:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except Exception:
        await message.answer(
            "🌐 <b>Выберите сайт для создания чека:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

@dp.callback_query(F.data == "site_cancel")
async def site_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Отменено.")
    await call.answer()

@dp.callback_query(F.data.startswith("site_pick:"))
async def site_picked(call: CallbackQuery, state: FSMContext):
    site_id = int(call.data.split(":")[1])
    site = await db.get_site(site_id)
    if not site or not site["active"]:
        await call.answer("Сайт недоступен.", show_alert=True); return
    await state.update_data(site_id=site_id, site_name=site["name"], site_domain=site["domain"], url_template=site.get("url_template", ""))
    await call.message.edit_text(
        f"💰 <b>Сайт: {site['name']}</b>",
        parse_mode="HTML",
    )
    from aiogram.types import FSInputFile
    try:
        photo = FSInputFile("crpayment.png")
        await call.message.answer_photo(
            photo=photo,
            caption="<b>Введите сумму в USDT:</b>",
            parse_mode="HTML",
            reply_markup=kb_cancel(),
        )
    except Exception:
        await call.message.answer(
            "<b>Введите сумму в USDT:</b>",
            parse_mode="HTML",
            reply_markup=kb_cancel(),
        )
    await state.set_state(InvoiceFSM.amount)
    await call.answer()

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

    data = await state.get_data()
    await state.update_data(amount=amount)

    # Для Coinbase нужны дополнительные данные от пользователя
    if "{d}" in data.get("url_template", ""):
        from aiogram.types import FSInputFile
        try:
            photo = FSInputFile("crpayment.png")
            await message.answer_photo(
                photo=photo,
                caption="👤 <b>Введите имя отправителя (поле From):</b>",
                parse_mode="HTML",
                reply_markup=kb_cancel(),
            )
        except Exception:
            await message.answer(
                "👤 <b>Введите имя отправителя (поле From):</b>",
                parse_mode="HTML",
                reply_markup=kb_cancel(),
            )
        await state.set_state(InvoiceFSM.from_name)
        return

    await _finish_invoice(message, state)


@dp.message(InvoiceFSM.from_name, F.text == "❌ Отмена")
async def invoice_from_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(InvoiceFSM.from_name)
async def invoice_from_name(message: Message, state: FSMContext):
    await state.update_data(from_name=message.text.strip())
    from aiogram.types import FSInputFile
    try:
        photo = FSInputFile("crpayment.png")
        await message.answer_photo(
            photo=photo,
            caption="💳 <b>Введите адрес кошелька получателя (Recipient address):</b>\n<i>Например: TQaHgZ...XVke</i>",
            parse_mode="HTML",
            reply_markup=kb_cancel(),
        )
    except Exception:
        await message.answer(
            "💳 <b>Введите адрес кошелька получателя (Recipient address):</b>\n<i>Например: TQaHgZ...XVke</i>",
            parse_mode="HTML",
            reply_markup=kb_cancel(),
        )
    await state.set_state(InvoiceFSM.wallet_address)

@dp.message(InvoiceFSM.wallet_address, F.text == "❌ Отмена")
async def invoice_wallet_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu())

@dp.message(InvoiceFSM.wallet_address)
async def invoice_wallet_address(message: Message, state: FSMContext):
    wallet = message.text.strip()
    if not wallet:
        await message.answer("❌ Адрес не может быть пустым. Введите адрес:"); return
    await state.update_data(wallet_address=wallet)
    await _finish_invoice(message, state)


async def _finish_invoice(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    user = await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name,
    )

    site_id = data["site_id"]
    site_name = data["site_name"]
    amount = data["amount"]
    from_name = data.get("from_name", user["tag"])
    wallet_address = data.get("wallet_address")

    token = await db.create_invoice(message.from_user.id, user["tag"], amount, site_id)
    site_full = await db.get_site(site_id)

    # Если пользователь ввёл wallet_address — подставляем в site для url_builder
    if wallet_address:
        site_full = dict(site_full)
        site_full["wallet_address"] = wallet_address

    try:
        link = build_invoice_url(site_full, token, amount, from_name)
    except ValueError as e:
        await message.answer(f"❌ Ошибка генерации ссылки: {e}", reply_markup=main_menu())
        return
    await db.increment_user_invoice_count(message.from_user.id)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    success_text = (
        f"✅ <b>Чек успешно создан!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🌐 Сайт: <b>{site_name}</b>\n"
        f"💰 Сумма: <b>{amount:.2f} USD</b>\n"
        f"🔑 Токен: <code>{token}</code>\n"
        f"📅 Создан: <b>{now}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 <b>Ссылка для оплаты:</b>\n<code>{link}</code>\n\n"
        f"⚠️ Сохраните ссылку перед тем как закрыть это сообщение!"
    )
    from aiogram.types import FSInputFile
    try:
        photo = FSInputFile("paymentcreated.png")
        await message.answer_photo(
            photo=photo,
            caption=success_text,
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
    except Exception:
        await message.answer(success_text, parse_mode="HTML", reply_markup=main_menu())

    tag_link = f"@{message.from_user.username}" if message.from_user.username else f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a>"
    notify_text = (
        f"🧾 <b>Новый чек создан</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👤 Воркер: {tag_link} | <b>{user['tag']}</b>\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🌐 Сайт: <b>{site_name}</b>\n"
        f"💰 Сумма: <b>{amount:.2f} USD</b>\n"
        f"🔑 Токен: <code>{token}</code>\n"
        f"🔗 Ссылка: {link}\n"
        f"📅 Время: <b>{now}</b>"
    )
    try:
        await bot.send_message(SUPPORT_CHAT_ID, notify_text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"Invoice notify error: {e}")


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
        lines.append(f"{icon} <code>{inv['token']}</code> — <b>{inv['amount']:.2f} USD</b> | {inv['created_at']}")

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
    status_icons = {"pending": "⏳", "paid": "✅", "expired": "❌"}
    lines = ["🧾 <b>Ваши последние чеки:</b>\n"]
    for inv in invoices:
        icon = status_icons.get(inv["status"], "▪️")
        site_name = inv.get("site_name", "—")
        lines.append(f"{icon} <b>{inv['amount']:.2f} USD</b> | {site_name} | <code>{inv['token']}</code> | {inv['created_at']}\n")
    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


# ════════════════════════════════════════════════════════════════════════════
# ПОЛЕЗНАЯ ИНФОРМАЦИЯ
# ════════════════════════════════════════════════════════════════════════════

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
        "📱 <b>Введите номер телефона</b>\n\nФормат: <code>+921111999922</code>",
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

@dp.callback_query(F.data == "noop")
async def noop(call: CallbackQuery): await call.answer()

@dp.callback_query(F.data == "done")
async def cb_done(call: CallbackQuery): await call.answer()


# ════════════════════════════════════════════════════════════════════════════
# АДМИН: УПРАВЛЕНИЕ САЙТАМИ
# ════════════════════════════════════════════════════════════════════════════

@dp.message(Command("sites"))
async def admin_sites(message: Message):
    if not is_admin(message.from_user.id): return
    sites = await db.get_all_sites()
    if not sites:
        await message.answer(
            "🌐 <b>Сайты для чеков</b>\n\nСписок пуст.\n\nДобавить: /addsite",
            parse_mode="HTML"
        ); return
    lines = ["🌐 <b>Сайты для чеков:</b>\n"]
    for s in sites:
        status = "✅" if s["active"] else "❌"
        template_short = s.get("url_template", "—")[:35] + ("…" if len(s.get("url_template","")) > 35 else "")
        wallet = s.get("wallet_address") or "—"
        if wallet != "—" and len(wallet) > 12:
            wallet = wallet[:8] + "…" + wallet[-4:]
        lines.append(
            f"{status} <b>{s['id']}. {s['name']}</b>\n"
            f"   🔗 <code>{s['domain']}</code>\n"
            f"   📋 {template_short}\n"
            f"   💳 {wallet}\n"
        )
    lines.append("\n/addsite — добавить\n/delsite ID — удалить\n/togglesite ID — вкл/выкл")
    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("addsite"))
async def admin_addsite_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    buttons = [
        [InlineKeyboardButton(text="🔴 Heleket",   callback_data="addsite_tpl:heleket")],
        [InlineKeyboardButton(text="🔵 Coinbase",  callback_data="addsite_tpl:coinbase")],
        [InlineKeyboardButton(text="🟣 Cryptomus", callback_data="addsite_tpl:cryptomus")],
        [InlineKeyboardButton(text="❌ Отмена",    callback_data="addsite_cancel")],
    ]
    await message.answer(
        "🌐 <b>Добавление сайта</b>\n\nШаг 1: Выберите шаблон:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(AddSiteFSM.template)


@dp.callback_query(AddSiteFSM.template, F.data.startswith("addsite_tpl:"))
async def addsite_template_chosen(call: CallbackQuery, state: FSMContext):
    preset_key = call.data.split(":")[1]
    url_template = TEMPLATE_PRESETS[preset_key]
    label = PRESET_LABELS[preset_key]
    await state.update_data(url_template=url_template, preset_key=preset_key)
    await call.message.edit_text(
        f"✅ Шаблон: <b>{label}</b>\n\nШаг 2: Введите название сайта:\n<i>Это название увидят воркеры при выборе сайта</i>",
        parse_mode="HTML",
    )
    await state.set_state(AddSiteFSM.name)
    await call.answer()


@dp.callback_query(F.data == "addsite_cancel")
async def addsite_cancel_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Отменено.")
    await call.answer()


@dp.message(AddSiteFSM.name, F.text == "❌ Отмена")
async def addsite_name_cancel(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())


@dp.message(AddSiteFSM.name)
async def addsite_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer(
        "Шаг 3: Введите домен сайта:\n<i>Например: https://pay.example.com</i>",
        parse_mode="HTML",
        reply_markup=kb_cancel(),
    )
    await state.set_state(AddSiteFSM.domain)


@dp.message(AddSiteFSM.domain, F.text == "❌ Отмена")
async def addsite_domain_cancel(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())


@dp.message(AddSiteFSM.domain)
async def addsite_domain(message: Message, state: FSMContext):
    domain = message.text.strip().rstrip("/")
    if not domain.startswith("http"):
        await message.answer("❌ Домен должен начинаться с http:// или https://\nПопробуйте снова:"); return
    data = await state.get_data()
    await state.update_data(domain=domain)

    # Для Coinbase wallet_address вводит пользователь при создании чека — не нужен в настройках сайта
    await _finish_addsite(message, state, wallet_address=None)


@dp.message(AddSiteFSM.wallet, F.text == "❌ Отмена")
async def addsite_wallet_cancel(message: Message, state: FSMContext):
    await state.clear(); await message.answer("Отменено.", reply_markup=main_menu())


@dp.message(AddSiteFSM.wallet)
async def addsite_wallet(message: Message, state: FSMContext):
    wallet = message.text.strip()
    if not wallet:
        await message.answer("❌ Адрес не может быть пустым. Введите адрес кошелька:"); return
    await _finish_addsite(message, state, wallet_address=wallet)


async def _finish_addsite(message: Message, state: FSMContext, wallet_address: str | None):
    data = await state.get_data()
    await state.clear()
    site_id = await db.add_site(
        name=data["name"],
        domain=data["domain"],
        url_template=data["url_template"],
        wallet_address=wallet_address,
    )
    label = PRESET_LABELS.get(data.get("preset_key", ""), data["url_template"])
    wallet_str = wallet_address[:8] + "…" + wallet_address[-4:] if wallet_address and len(wallet_address) > 12 else (wallet_address or "—")
    await message.answer(
        f"✅ <b>Сайт добавлен!</b>\n\n"
        f"🆔 ID: <b>{site_id}</b>\n"
        f"📛 Название: <b>{data['name']}</b>\n"
        f"🔗 Домен: <code>{data['domain']}</code>\n"
        f"📋 Шаблон: <b>{label}</b>\n"
        f"💳 Кошелёк: <b>{wallet_str}</b>\n"
        f"✅ Статус: Активен",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@dp.message(Command("delsite"))
async def admin_delsite(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /delsite ID"); return
    try:
        site_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом."); return
    # Проверяем наличие чеков
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM invoices WHERE site_id=$1", site_id)
    if count and count > 0:
        await message.answer(
            f"⚠️ У сайта #{site_id} есть <b>{count}</b> чеков.\n\n"
            f"Для подтверждения удаления напишите:\n<code>/delsite_confirm {site_id}</code>",
            parse_mode="HTML",
        ); return
    ok = await db.delete_site(site_id)
    await message.answer(f"✅ Сайт #{site_id} удалён." if ok else f"❌ Сайт #{site_id} не найден.")


@dp.message(Command("delsite_confirm"))
async def admin_delsite_confirm(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /delsite_confirm ID"); return
    try:
        site_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом."); return
    ok = await db.delete_site(site_id)
    await message.answer(f"✅ Сайт #{site_id} удалён." if ok else f"❌ Сайт #{site_id} не найден.")


@dp.message(Command("togglesite"))
async def admin_togglesite(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /togglesite ID"); return
    try:
        site_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом."); return
    site = await db.toggle_site(site_id)
    if not site:
        await message.answer(f"❌ Сайт #{site_id} не найден."); return
    status = "✅ Активен" if site["active"] else "❌ Отключён"
    await message.answer(f"🔄 Сайт <b>{site['name']}</b>: {status}", parse_mode="HTML")


# ════════════════════════════════════════════════════════════════════════════
# АДМИН: ОСНОВНЫЕ КОМАНДЫ
# ════════════════════════════════════════════════════════════════════════════

@dp.message(Command("adminhelp"))
async def admin_help(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer(
        "📋 <b>Все админские команды:</b>\n\n"
        "━━ Режим работы ━━\n"
        "/setmode день|ночь|стоп\n\n"
        "━━ Сайты для чеков ━━\n"
        "/sites — список сайтов\n"
        "/addsite — добавить сайт\n"
        "/delsite ID — удалить сайт\n"
        "/togglesite ID — вкл/выкл сайт\n"
        "/sitestats — статистика по сайтам\n"
        "/sitestats ID — детальная статистика\n\n"
        "━━ Чеки ━━\n"
        "/invoices — последние 20 чеков\n\n"
        "━━ Выплаты ━━\n"
        "/pay тег 500\n"
        "/delpay тег 500\n"
        "/setpct 70 — процент всем\n"
        "/setpct тег 70 — конкретному\n"
        "/setcash 1234\n\n"
        "━━ Пользователи ━━\n"
        "/userinfo тег\n"
        "/ban тег [причина]\n"
        "/unban тег\n\n"
        "━━ Саппорты ━━\n"
        "/addsupport @username\n"
        "/delsupport @username\n\n"
        "━━ Наставники ━━\n"
        "/addmentor тег @username процент\n"
        "/delmentor тег\n"
        "/delmentorglobal тег\n"
        "/setmentorfee тег процент\n"
        "/setmentorbio тег текст\n\n"
        "━━ Роли (инструктаж) ━━\n"
        "/setrole creator|moderator|developer @username\n"
        "/setmentors @user1 @user2\n\n"
        "━━ Рассылка ━━\n"
        "/broadcast\n",
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

@dp.message(Command("invoices"))
async def admin_invoices(message: Message):
    if not is_admin(message.from_user.id): return
    invoices = await db.get_all_invoices(limit=20)
    if not invoices:
        await message.answer("📭 Чеков нет."); return
    status_icons = {"pending": "⏳", "paid": "✅", "expired": "❌"}
    lines = ["🧾 <b>Последние 20 чеков:</b>\n"]
    for inv in invoices:
        icon = status_icons.get(inv["status"], "▪️")
        site_name = inv.get("site_name", "—")
        lines.append(
            f"{icon} <b>{inv['user_tag']}</b> | <b>{inv['amount']:.2f} USD</b> | {site_name}\n"
            f"   🔑 <code>{inv['token']}</code> | 📅 {inv['created_at']}\n"
        )
    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)

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

    if mentor_info.get("mentor_id"):
        try:
            removed_text = "\n\n✅ Обучение завершено — ученик снят." if mentor_info.get("mentor_removed") else ""
            await bot.send_message(
                mentor_info["mentor_id"],
                f"💰 <b>Вам начислена доля от выплаты!</b>\n\nУченик: <b>{tag}</b>\nВаш процент: <b>{mentor_info['fee_pct']}%</b>\nВаша доля: <b>{fmt(mentor_info['mentor_fee'])} USDT</b>{removed_text}",
                parse_mode="HTML",
            )
        except Exception: pass

    mentor_channel_line = f"\n👨‍🏫 Доля наставника @{mentor_info['mentor_username']} ({mentor_info['fee_pct']}%): <b>{fmt(mentor_info['mentor_fee'])} USDT</b>" if mentor_info.get("mentor_id") else ""
    payout_text = f"💳 <b>Новая оплата</b>\n\n👤 Тег: <b>{tag}</b>\n💰 Сумма: <b>{fmt(amount)} USDT</b>\n📊 Доля воркера ({int(pct)}%): <b>{fmt(worker_share)} USDT</b>{mentor_channel_line}"
    try:
        from aiogram.types import FSInputFile
        photo = FSInputFile("newpayment.png")
        sent = await bot.send_photo(PAYOUTS_CHANNEL, photo=photo, caption=payout_text, parse_mode="HTML")
    except Exception:
        sent = await bot.send_message(PAYOUTS_CHANNEL, payout_text, parse_mode="HTML")
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
        f"💰 Сумма выплат: <b>{user['payout_sum']:.2f} USDT</b>\n"
        f"🧾 Кол-во выплат: <b>{user['payout_count']}</b>\n"
        f"📊 Процент выплат: <b>{int(user['payout_pct'])}%</b>\n"
        f"🤝 Наставник: <b>{mentor_str}</b>"
    )
    await message.answer(text, parse_mode="HTML")

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

@dp.message(Command("addmentor"))
async def admin_addmentor(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=4)
    if len(args) < 4:
        await message.answer("Использование: /addmentor тег @username процент [описание]"); return
    tag = args[1].lstrip("@"); username = args[2].lstrip("@")
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
    await message.answer(f"✅ Комиссия наставника <b>{args[1]}</b>: <b>{fee}%</b>", parse_mode="HTML")

@dp.message(Command("setmentorbio"))
async def admin_setmentorbio(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: /setmentorbio тег текст"); return
    mentor = await db.get_mentor_by_tag(args[1].lstrip("@"))
    if not mentor:
        await message.answer("❌ Наставник не найден."); return
    await db.set_mentor_bio(mentor["user_id"], args[2])
    await message.answer("✅ Описание наставника обновлено.")

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
    await message.answer(f"✅ <code>{new_admin_id}</code> добавлен как администратор.", parse_mode="HTML")
    try: await bot.send_message(new_admin_id, "✅ <b>Вам выданы права администратора.</b>", parse_mode="HTML")
    except Exception: pass

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

@dp.message(Command("mystats"))
async def cmd_mystats(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Вы не зарегистрированы."); return
    invoices = await db.get_user_invoices(message.from_user.id, limit=100)
    total_inv = len(invoices)
    text = (
        f"📊 <b>Ваша статистика</b> — <b>{user['tag']}</b>\n\n"
        f"🧾 Чеков создано: <b>{total_inv}</b>\n"
        f"💰 Сумма выплат: <b>{user['payout_sum']:.2f} USDT</b>\n"
        f"🧾 Кол-во выплат: <b>{user['payout_count']}</b>"
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("sitestats"))
async def admin_sitestats(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()

    if len(args) == 2:
        # Детальная статистика по конкретному сайту
        try:
            site_id = int(args[1])
        except ValueError:
            await message.answer("Использование: /sitestats [ID]"); return
        data = await db.get_site_stats_detail(site_id)
        if not data:
            await message.answer(f"❌ Сайт #{site_id} не найден."); return
        site = data["site"]
        top_lines = "\n".join(
            f"   {i+1}. <b>{w['user_tag']}</b> — {w['cnt']} чеков"
            for i, w in enumerate(data["top_workers"])
        ) or "   Нет данных"
        await message.answer(
            f"📊 <b>Статистика: {site['name']}</b>\n\n"
            f"🧾 Всего чеков: <b>{data['count_total']}</b>\n"
            f"💰 Общая сумма: <b>{data['sum_total']:.2f} USD</b>\n\n"
            f"📋 По статусам:\n"
            f"   ⏳ Ожидают: <b>{data['pending']}</b>\n"
            f"   ✅ Оплачены: <b>{data['paid']}</b>\n"
            f"   ❌ Истекли: <b>{data['expired']}</b>\n\n"
            f"🏆 Топ-5 воркеров:\n{top_lines}",
            parse_mode="HTML",
        )
        return

    # Общая статистика по всем сайтам
    stats = await db.get_site_stats_all()
    if not stats:
        await message.answer("📊 Нет данных по сайтам."); return
    lines = ["📊 <b>Статистика по сайтам:</b>\n"]
    for s in stats:
        lines.append(
            f"🌐 <b>{s['name']}</b>\n"
            f"   Сегодня: <b>{s['count_today']}</b> чеков\n"
            f"   Всего: <b>{s['count_total']}</b> чеков | <b>{float(s['sum_total']):.2f} USD</b>\n"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── Run ─────────────────────────────────────────────────────────────────────

async def main():
    await db.init_db()
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
