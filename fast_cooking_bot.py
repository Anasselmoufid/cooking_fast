import asyncio
import logging
import os
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from youtube_search_python import VideosSearch
import pandas as pd

# ──────────────── إعدادات ────────────────
TOKEN = os.environ["8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"]
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

EXCEL_FILE = "youtube_recipes.xlsx"
saved_recipes = []

# ──────────────── لوحة المفاتيح الدائمة ────────────────
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 بحث عن وصفة")],
            [KeyboardButton(text="🍳 وصفة عشوائية")],
            [KeyboardButton(text="📊 الوصفات المحفوظة")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

# ──────────────── تخمين الدولة والقارة من العنوان ────────────────
COUNTRY_MAP = {
    "moroccan": "المغرب", "egyptian": "مصر", "tunisian": "تونس",
    "indian": "الهند", "italian": "إيطاليا", "mexican": "المكسيك",
    "thai": "تايلاند", "chinese": "الصين", "japanese": "اليابان",
    "american": "أمريكا", "british": "بريطانيا", "french": "فرنسا"
}

CONTINENT_MAP = {
    "المغرب": "أفريقيا", "مصر": "أفريقيا", "تونس": "أفريقيا",
    "الهند": "آسيا", "الصين": "آسيا", "اليابان": "آسيا",
    "إيطاليا": "أوروبا", "فرنسا": "أوروبا", "بريطانيا": "أوروبا",
    "أمريكا": "أمريكا الشمالية", "المكسيك": "أمريكا الشمالية"
}

def guess_country(title: str):
    title_lower = title.lower()
    for key, country in COUNTRY_MAP.items():
        if key in title_lower:
            return country, CONTINENT_MAP.get(country, "العالم")
    return "غير معروف", "العالم"

# ──────────────── بحث في يوتيوب فقط ────────────────
async def search_youtube(query: str):
    search = VideosSearch(query, limit=8)
    results = []

    for video in search.result()["result"]:
        country, continent = guess_country(video["title"])
        results.append({
            "title": video["title"],
            "channel": video["channel"]["name"],
            "duration": video.get("duration", "?"),
            "views": video.get("viewCount", "غير معروف"),
            "link": f"https://youtube.com/watch?v={video['id']}",
            "thumbnail": video["thumbnails"][0]["url"],
            "country": country,
            "continent": continent
        })
    return results

# ──────────────── تنسيق الوصف الشامل ────────────────
def format_video(video):
    text = f"""
🎥 **{video["title"]}**

📍 الدولة: {video["country"]}
🌍 القارة: {video["continent"]}
👤 القناة: {video["channel"]}
⏱ المدة: {video["duration"]}
👁 المشاهدات: {video["views"]}
    """.strip()
    return text

# ──────────────── حفظ في Excel ────────────────
def save_to_excel(video, user_id, username):
    row = {
        "التاريخ": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "العنوان": video["title"],
        "الدولة": video["country"],
        "القارة": video["continent"],
        "القناة": video["channel"],
        "المدة": video["duration"],
        "المشاهدات": video["views"],
        "الرابط": video["link"],
        "User ID": user_id,
        "Username": username or "غير معروف"
    }
    saved_recipes.append(row)
    pd.DataFrame(saved_recipes).to_excel(EXCEL_FILE, index=False)

# ──────────────── البداية ────────────────
@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "🌍 مرحباً في بوت يوتيوب الوصفات الشامل!\n\n"
        "اكتب اسم أي وجبة أو وصفة تريدها (بالعربية أو الإنجليزية)\n"
        "مثال: كسكس، برجر، سوشي، فول مدمس، chicken biryani",
        reply_markup=main_keyboard()
    )

@router.message(lambda m: m.text == "🔍 بحث عن وصفة")
async def ask_search(message: types.Message):
    await message.answer("اكتب اسم الوصفة أو الوجبة التي تريدها:")

@router.message()
async def youtube_search_handler(message: types.Message):
    query = message.text.strip()

    if query == "📊 الوصفات المحفوظة":
        if os.path.exists(EXCEL_FILE):
            await message.answer_document(types.FSInputFile(EXCEL_FILE), caption="📊 جميع الوصفات المحفوظة")
        else:
            await message.answer("لا توجد وصفات محفوظة بعد.")
        return

    await message.answer(f"🔎 جاري البحث في يوتيوب عن: {query}")

    results = await search_youtube(query)

    if not results:
        await message.answer("لم أجد نتائج. جرب كتابة الاسم بطريقة أخرى.")
        return

    for video in results:
        text = format_video(video)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ مشاهدة الفيديو على يوتيوب", url=video["link"])]
        ])
        await message.answer_photo(photo=video["thumbnail"], caption=text, reply_markup=kb)
        save_to_excel(video, message.from_user.id, message.from_user.username)

    await message.answer("اكتب وصفة جديدة أو اختر من الأزرار أدناه:", reply_markup=main_keyboard())

# ──────────────── Webhook Setup ────────────────
async def on_startup():
    await bot.delete_webhook(drop_pending_updates=True)
    webhook_url = f"https://{os.environ['RENDER_EXTERNAL_HOSTNAME']}/webhook"
    await bot.set_webhook(webhook_url)
    print(f"Webhook set to: {webhook_url}")

app = web.Application()
webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
webhook_handler.register(app, path="/webhook")
setup_application(app, dp, bot=bot)

async def main():
    await on_startup()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000)))
    await site.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

