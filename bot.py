import html
import logging
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

import config
import db
import service
from grading import parse_key_string

log = logging.getLogger("bot")
router = Router()

bot = Bot(config.BOT_TOKEN) if config.BOT_TOKEN else None
dp = Dispatcher()
dp.include_router(router)

HELP_ANSWER = (
    "📌 <b>Testga javob berishning 3 oson usuli:</b>\n\n"
    "1️⃣ <b>Tugma orqali:</b>\n\"✅ Testga javob berish\" tugmasini bosing.\n\n"
    "2️⃣ <b>Test kodi orqali:</b>\nFaqat test raqamini yozing.\nMasalan: <code>13</code>\n\n"
    "3️⃣ <b>Kalit bilan:</b>\nTest raqamidan keyin * qo'shing va barcha javob kalitlarini yozing.\n"
    "Masalan: <code>123*abcdabcd...</code>\n\n"
    "✅ Katta va kichik harflar farqi yo'q.\n"
    "❗ Har bir testga faqat bir marta javob berishingiz mumkin."
)

HELP_CREATE = (
    "1️⃣ Test nomini yozing va + belgisini yozing.\n"
    "2️⃣ Javob kalitlarini yozing.\n\n"
    "✍️ <b>Misol:</b>\n<code>Yangitest+abcdabcd...</code>\n<code>Yangitest+1a2b3c4d5a6b7c...</code>\n\n"
    "✅ Katta va kichik harflar bir xil hisoblanadi.\n"
    "Shu yerda \"⚡ Test tuzish ⚡\" tugmasi orqali ham test tuzishingiz mumkin."
)


def can_create(user_id: int) -> bool:
    return (not config.ADMIN_IDS) or user_id in config.ADMIN_IDS


def main_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="✅ Testga javob berish", callback_data="answer_help")]]
    if can_create(user_id):
        rows.append([InlineKeyboardButton(text="⚡ Test tuzish ⚡", web_app=WebAppInfo(url=f"{config.BASE_URL}/app/create"))])
    rows.append([InlineKeyboardButton(text="🔤 Testga qanday javob beriladi?", callback_data="answer_help")])
    rows.append([InlineKeyboardButton(text="Botda test ishlash va tuzish (+video)", callback_data="video")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def open_test_kb(code: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📝 Javoblarni belgilash", web_app=WebAppInfo(url=f"{config.BASE_URL}/app/answer?code={code}"))]]
    )


@router.message(Command("start"))
async def cmd_start(m: Message):
    db.upsert_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    await m.answer(
        f"Assalomu alaykum, {html.escape(m.from_user.first_name)}! 👋\n\n" + HELP_ANSWER,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="✅ Testga javob berish", callback_data="answer_help")]]
        ),
    )
    await m.answer(HELP_CREATE, parse_mode="HTML", reply_markup=main_kb(m.from_user.id))


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(HELP_ANSWER + "\n\n" + HELP_CREATE, parse_mode="HTML", reply_markup=main_kb(m.from_user.id))


@router.message(Command("natijalarim"))
async def cmd_my(m: Message):
    with db.conn() as c:
        rows = c.execute(
            "SELECT s.test_code, s.correct_count, s.total, t.title FROM submissions s "
            "JOIN tests t ON t.code=s.test_code WHERE s.tg_id=? ORDER BY s.created_at DESC LIMIT 20",
            (m.from_user.id,),
        ).fetchall()
    if not rows:
        await m.answer("Hali birorta testga javob bermagansiz.")
        return
    text = "📋 <b>So'nggi natijalaringiz:</b>\n\n" + "\n".join(
        f"• {html.escape(r['title'])} (kod {r['test_code']}): {r['correct_count']}/{r['total']}" for r in rows
    )
    await m.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "answer_help")
async def cb_answer_help(c: CallbackQuery):
    await c.message.answer("Test raqamini (kodini) yozing. Masalan: <code>13</code>", parse_mode="HTML")
    await c.answer()


@router.callback_query(F.data == "video")
async def cb_video(c: CallbackQuery):
    await c.message.answer(HELP_ANSWER + "\n\n" + HELP_CREATE, parse_mode="HTML")
    await c.answer()


# --- Test kodi: faqat raqam ---
@router.message(F.text.regexp(r"^\s*\d+\s*$"))
async def by_code(m: Message):
    db.upsert_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    code = int(m.text.strip())
    test = db.get_test(code)
    if not test:
        await m.answer(service.STATUS_TEXT["notfound"])
        return
    if not test["is_active"]:
        await m.answer(service.STATUS_TEXT["inactive"])
        return
    if db.get_submission(code, m.from_user.id):
        await m.answer(service.STATUS_TEXT["duplicate"])
        return
    await m.answer(
        f"📝 <b>{html.escape(test['title'])}</b>\nKod: {code} · {len(test['answers'])} ta savol\n\nJavoblarni belgilash uchun tugmani bosing.",
        parse_mode="HTML",
        reply_markup=open_test_kb(code),
    )


# --- Kalit bilan: 123*abcd ---
@router.message(F.text.regexp(r"^\s*\d+\s*\*"))
async def by_key(m: Message):
    db.upsert_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    head, _, tail = m.text.partition("*")
    code = int(head.strip())
    keys = parse_key_string(tail)
    if not keys:
        await m.answer("❌ Javob kalitlari noto'g'ri. Masalan: <code>123*abcdabcd</code>", parse_mode="HTML")
        return
    test = db.get_test(code)
    if test and len(keys) != len(test["answers"]):
        await m.answer(f"❌ Bu testda {len(test['answers'])} ta savol bor, siz {len(keys)} ta javob yozdingiz.")
        return
    given = [k["value"] for k in keys]
    res = service.submit(code, m.from_user.id, given)
    if res["status"] != "ok":
        await m.answer(service.STATUS_TEXT[res["status"]])
        return
    await m.answer(res["text"], parse_mode="HTML")


# --- Yangi test: Nomi+abcd ---
@router.message(F.text.contains("+"))
async def create_by_text(m: Message):
    if not can_create(m.from_user.id):
        await m.answer("⛔ Test tuzish faqat o'qituvchilar uchun.")
        return
    title, _, tail = m.text.partition("+")
    title = title.strip()
    keys = parse_key_string(tail)
    if not title or not keys:
        await m.answer(HELP_CREATE, parse_mode="HTML")
        return
    options = 5 if any(k["value"] == "e" for k in keys) else 4
    code = db.create_test(title, keys, options=options, owner_id=m.from_user.id)
    await m.answer(created_text(title, code, len(keys)), parse_mode="HTML")


def created_text(title: str, code: int, total: int) -> str:
    return (
        f"✅ <b>Test tuzildi!</b>\n\n📝 Nomi: {html.escape(title)}\n🔑 Kod: <code>{code}</code>\n"
        f"❓ Savollar: {total} ta\n\nO'quvchilar botga <code>{code}</code> raqamini yozib javob berishadi."
    )


@router.message()
async def fallback(m: Message):
    await m.answer(HELP_ANSWER, parse_mode="HTML", reply_markup=main_kb(m.from_user.id))


async def setup():
    service.set_bot(bot)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Botni ishga tushirish"),
            BotCommand(command="help", description="Yordam"),
            BotCommand(command="natijalarim", description="Mening natijalarim"),
        ]
    )
