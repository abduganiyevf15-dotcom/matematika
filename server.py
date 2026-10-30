import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import bot as botmod
import config
import db
import service

logging.basicConfig(level=logging.INFO)
BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


def _dt(ts):
    import datetime
    if not ts:
        return "—"
    tz = datetime.timezone(datetime.timedelta(hours=5))
    return datetime.datetime.fromtimestamp(int(ts), tz).strftime("%d.%m.%Y %H:%M")


templates.env.filters["dt"] = _dt


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    task = None
    if botmod.bot is not None:
        await botmod.setup()
        task = asyncio.create_task(botmod.dp.start_polling(botmod.bot))
        logging.info("Telegram bot ishga tushdi (polling)")
    else:
        logging.warning("BOT_TOKEN berilmagan: faqat web ilova va admin panel ishlaydi")
    yield
    if task:
        task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
security = HTTPBasic()


# ---------- Telegram mini app autentifikatsiyasi ----------
def verify_init_data(init_data: str):
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        got_hash = parsed.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got_hash):
            return None
        if time.time() - int(parsed.get("auth_date", 0)) > 86400:
            return None
        return json.loads(parsed["user"])
    except Exception:
        return None


def get_user(init_data: str, dev_user):
    if not config.VERIFY_INIT_DATA:
        return {"id": int(dev_user or 1), "first_name": "Dev", "username": "dev"}
    return verify_init_data(init_data or "")


def admin_auth(creds: HTTPBasicCredentials = Depends(security)):
    ok = secrets.compare_digest(creds.username, config.ADMIN_USER) and secrets.compare_digest(
        creds.password, config.ADMIN_PASSWORD
    )
    if not ok:
        raise HTTPException(401, "Noto'g'ri login yoki parol", headers={"WWW-Authenticate": "Basic"})
    return True


def clean_keys(raw, options):
    """Brauzerdan kelgan kalitlarni tekshirib, saqlanadigan ko'rinishga keltiradi."""
    keys = []
    letters = "abcde"[:options]
    for k in raw:
        if k.get("type") == "open":
            vals = [v.strip() for v in k.get("values", []) if str(v).strip()]
            if not vals:
                raise ValueError("Ochiq javob bo'sh")
            keys.append({"type": "open", "values": vals})
        else:
            v = str(k.get("value", "")).lower()
            if v not in letters:
                raise ValueError("Javob varianti noto'g'ri")
            keys.append({"type": "choice", "value": v})
    if not 1 <= len(keys) <= 200:
        raise ValueError("Savollar soni 1 dan 200 gacha bo'lishi kerak")
    return keys


# ---------- Mini app sahifalari ----------
@app.get("/app/answer")
async def page_answer():
    return FileResponse(BASE / "static" / "answer.html")


@app.get("/app/create")
async def page_create(request: Request):
    return templates.TemplateResponse(
        request, "builder.html",
        {"mode": "app", "initial": None, "endpoint": "/api/create", "method": "POST", "redirect": "", "code": None},
    )


# ---------- Mini app API ----------
@app.get("/api/test/{code}")
async def api_test(code: int):
    t = db.get_test(code)
    if not t:
        return JSONResponse({"error": "notfound"}, status_code=404)
    has_open = any(k["type"] == "open" for k in t["answers"])
    return {
        "code": t["code"],
        "title": t["title"],
        "count": len(t["answers"]),
        "options": t["options"],
        "open": has_open or bool(t["math_keyboard"]),
        "math_keyboard": bool(t["math_keyboard"]) or has_open,
        "active": bool(t["is_active"]),
    }


@app.post("/api/submit")
async def api_submit(request: Request):
    body = await request.json()
    user = get_user(body.get("initData"), body.get("dev_user"))
    if not user:
        raise HTTPException(401, "Telegram orqali oching")
    db.upsert_user(user["id"], " ".join(filter(None, [user.get("first_name"), user.get("last_name")])), user.get("username"))
    res = service.submit(int(body["code"]), user["id"], body.get("answers", []))
    if res["status"] != "ok":
        return JSONResponse({"status": res["status"], "message": service.STATUS_TEXT[res["status"]]}, status_code=409)
    await service.notify(user["id"], res["text"])
    return {"status": "ok", "correct": res["correct"], "total": res["total"]}


@app.post("/api/create")
async def api_create(request: Request):
    body = await request.json()
    user = get_user(body.get("initData"), body.get("dev_user"))
    if not user:
        raise HTTPException(401, "Telegram orqali oching")
    if config.ADMIN_IDS and user["id"] not in config.ADMIN_IDS:
        raise HTTPException(403, "Test tuzish faqat o'qituvchilar uchun")
    try:
        options = 5 if int(body.get("options", 4)) == 5 else 4
        keys = clean_keys(body["keys"], options)
        title = str(body.get("title", "")).strip()[:100]
        if not title:
            raise ValueError("Test nomini yozing")
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    code = db.create_test(title, keys, options, bool(body.get("math")), owner_id=user["id"])
    await service.notify(user["id"], botmod.created_text(title, code, len(keys)))
    return {"code": code}


# ---------- Admin panel ----------
@app.get("/admin")
async def admin_home(request: Request, _=Depends(admin_auth)):
    return templates.TemplateResponse(
        request, "dashboard.html", {"stats": db.stats(), "tests": db.list_tests(), "page": "tests"}
    )


@app.get("/admin/tests/new")
async def admin_new(request: Request, _=Depends(admin_auth)):
    return templates.TemplateResponse(
        request, "builder.html",
        {"mode": "admin", "initial": None, "endpoint": "/admin/api/tests", "method": "POST", "redirect": "/admin", "code": None, "page": "tests"},
    )


@app.get("/admin/tests/{code}/edit")
async def admin_edit(code: int, request: Request, _=Depends(admin_auth)):
    t = db.get_test(code)
    if not t:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request, "builder.html",
        {"mode": "admin", "initial": t, "endpoint": f"/admin/api/tests/{code}", "method": "PUT", "redirect": "/admin", "code": code, "page": "tests"},
    )


@app.post("/admin/api/tests")
async def admin_api_create(request: Request, _=Depends(admin_auth)):
    body = await request.json()
    try:
        options = 5 if int(body.get("options", 4)) == 5 else 4
        keys = clean_keys(body["keys"], options)
        title = str(body.get("title", "")).strip()[:100]
        if not title:
            raise ValueError("Test nomini yozing")
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    code = db.create_test(title, keys, options, bool(body.get("math")))
    return {"code": code}


@app.put("/admin/api/tests/{code}")
async def admin_api_update(code: int, request: Request, _=Depends(admin_auth)):
    body = await request.json()
    t = db.get_test(code)
    if not t:
        raise HTTPException(404)
    try:
        options = 5 if int(body.get("options", 4)) == 5 else 4
        keys = clean_keys(body["keys"], options)
        title = str(body.get("title", "")).strip()[:100]
        if not title:
            raise ValueError("Test nomini yozing")
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    db.update_test(code, title, keys, options, bool(body.get("math")), t["is_active"])
    return {"code": code}


@app.post("/admin/tests/{code}/toggle")
async def admin_toggle(code: int, _=Depends(admin_auth)):
    t = db.get_test(code)
    if t:
        db.update_test(code, t["title"], t["answers"], t["options"], t["math_keyboard"], not t["is_active"])
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/tests/{code}/delete")
async def admin_delete(code: int, _=Depends(admin_auth)):
    db.delete_test(code)
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/tests/{code}/results")
async def admin_results(code: int, request: Request, _=Depends(admin_auth)):
    t = db.get_test(code)
    if not t:
        raise HTTPException(404)
    rows = db.results_for(code)
    for r in rows:
        r["pct"] = round(r["correct_count"] * 100 / r["total"]) if r["total"] else 0
    avg = round(sum(r["pct"] for r in rows) / len(rows)) if rows else 0
    return templates.TemplateResponse(
        request, "results.html", {"test": t, "rows": rows, "avg": avg, "page": "tests"}
    )


@app.post("/admin/tests/{code}/reset/{tg_id}")
async def admin_reset(code: int, tg_id: int, _=Depends(admin_auth)):
    db.reset_submission(code, tg_id)
    return RedirectResponse(f"/admin/tests/{code}/results", status_code=303)


@app.get("/admin/users")
async def admin_users(request: Request, _=Depends(admin_auth)):
    return templates.TemplateResponse(request, "users.html", {"users": db.list_users(), "page": "users"})


@app.get("/")
async def root():
    return RedirectResponse("/admin")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=int(__import__("os").getenv("PORT", "8000")))
