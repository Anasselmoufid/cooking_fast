import asyncio
import logging
import os
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from youtube_search_python import VideosSearch
import pandas as pd

# ──────────────── إعدادات ────────────────
TOKEN = os.environ.get("8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ")
if not TOKEN:
    raise ValueError("BOT_TOKEN غير موجود في Environment Variables!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

EXCEL_FILE = "youtube-search-python"
saved_recipes = []

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 بحث عن وصفة")],
            [KeyboardButton(text="📊 الوصفات المحفوظة")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

async def search_youtube(query: str):
    search = VideosSearch(query, limit=6)
    results = []
    for video in search.result()["result"]:
        results.append({
            "title": video["title"],
            "channel": video["channel"]["name"],
            "duration": video.get("duration", "?"),
            "views": video.get("viewCount", "غير معروف"),
            "link": f"https://youtube.com/watch?v={video['id']}",
            "thumbnail": video["thumbnails"][0]["url"]
        })
    return results

def format_video(video):
    return f"""
🎥 {video["title"]}
👤 {video["channel"]}
⏱ {video["duration"]} | 👁 {video["views"]}
🔗 {video["link"]}
    """.strip()

@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "مرحباً! اكتب اسم أي وصفة أو وجبة تريدها (بالعربية أو الإنجليزية)",
        reply_markup=main_keyboard()
    )

@router.message()
async def handle_message(message: types.Message):
    query = message.text.strip()

    if query == "📊 الوصفات المحفوظة":
        if os.path.exists(EXCEL_FILE):
            await message.answer_document(types.FSInputFile(EXCEL_FILE))
        else:
            await message.answer("لا توجد وصفات محفوظة بعد.")
        return

    await message.answer(f"جاري البحث في يوتيوب عن: {query}")

    results = await search_youtube(query)

    if not results:
        await message.answer("لم أجد نتائج. جرب كتابة الاسم بطريقة مختلفة.")
        return

    for v in results:
        text = format_video(v)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ مشاهدة الفيديو", url=v["link"])]
        ])
        await message.answer_photo(photo=v["thumbnail"], caption=text, reply_markup=kb)

    await message.answer("اكتب وصفة جديدة:", reply_markup=main_keyboard())

# ──────────────── Webhook Setup (بسيط وآمن) ────────────────
async def on_startup():
    await bot.delete_webhook(drop_pending_updates=True)
    # لو مش عايز webhook دلوقتي، استخدم polling مؤقتًا للاختبار
    print("البوت جاهز – جرب /start")

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
    print(f"Server running on port {os.environ.get('PORT', 10000)}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

