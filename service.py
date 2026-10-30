import html
import logging

import db
from grading import grade

log = logging.getLogger("service")

_bot = None


def set_bot(bot):
    global _bot
    _bot = bot


async def notify(tg_id: int, text: str, **kwargs):
    if _bot is None:
        log.info("[bot yo'q] %s -> %s", tg_id, text)
        return
    try:
        await _bot.send_message(tg_id, text, parse_mode="HTML", **kwargs)
    except Exception as e:  # foydalanuvchi botni bloklagan bo'lishi mumkin
        log.warning("Xabar yuborilmadi (%s): %s", tg_id, e)


def format_result(test: dict, correct: int, total: int, details: list) -> str:
    pct = round(correct * 100 / total) if total else 0
    wrong = [str(d["n"]) for d in details if not d["ok"]]
    lines = [
        f"📊 <b>{html.escape(test['title'])}</b> (kod: {test['code']})",
        "",
        f"✅ To'g'ri javoblar: <b>{correct} / {total}</b> ({pct}%)",
    ]
    if wrong:
        lines.append("❌ Xato yoki javobsiz: " + ", ".join(wrong))
    else:
        lines.append("🎉 Barcha javoblar to'g'ri!")
    return "\n".join(lines)


def submit(code: int, tg_id: int, given: list) -> dict:
    """Javoblarni tekshiradi va saqlaydi. Har bir testga bir marta."""
    test = db.get_test(code)
    if not test:
        return {"status": "notfound"}
    if not test["is_active"]:
        return {"status": "inactive"}
    if db.get_submission(code, tg_id):
        return {"status": "duplicate"}
    given = [(g if g not in ("", None) else None) for g in given]
    correct, details = grade(test["answers"], given)
    total = len(test["answers"])
    if not db.save_submission(code, tg_id, given, correct, total):
        return {"status": "duplicate"}
    return {
        "status": "ok",
        "test": test,
        "correct": correct,
        "total": total,
        "details": details,
        "text": format_result(test, correct, total, details),
    }


STATUS_TEXT = {
    "notfound": "❌ Bunday kodli test topilmadi.",
    "inactive": "⛔ Bu test yopilgan.",
    "duplicate": "❗ Siz bu testga allaqachon javob bergansiz. Har bir testga faqat bir marta javob berish mumkin.",
}
