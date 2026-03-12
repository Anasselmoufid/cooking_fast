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

import pandas as pd
from youtubesearchpython import VideosSearch

# ──────────────── إعدادات ────────────────
TOKEN = "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"                     # توكن البوت
SPOONACULAR_KEY = "bd7328461e664336834eb1e43e82b248"     # ← ضع مفتاح Spoonacular هنا

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

EXCEL_FILE = "recipes.xlsx"
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

# ──────────────── بحث شامل (الإنترنت + يوتيوب) ────────────────
async def search_full_internet(query: str):
    # 1. بحث في Spoonacular (الإنترنت كامل)
    url = f"https://api.spoonacular.com/recipes/complexSearch?query={query}&number=6&addRecipeInformation=true&apiKey={SPOONACULAR_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get("results", [])
            else:
                results = []

    # 2. بحث في يوتيوب
    yt_search = VideosSearch(f"{query} وصفة", limit=4)
    yt_results = []
    for v in yt_search.result()["result"]:
        yt_results.append({
            "title": v["title"],
            "channel": v["channel"]["name"],
            "link": f"https://youtube.com/watch?v={v['id']}",
            "thumbnail": v["thumbnails"][0]["url"]
        })

    return results, yt_results

def format_recipe(recipe):
    title = recipe.get("title", "غير معروف")
    time = recipe.get("readyInMinutes", "?")
    servings = recipe.get("servings", "?")
    ingredients = [i["original"] for i in recipe.get("extendedIngredients", [])][:15]

    text = f"""
🍽 **{title}**

⏱ وقت التحضير: {time} دقيقة
👥 لـ {servings} أشخاص

📋 المكونات:
• {'\n• '.join(ingredients)}
    """.strip()

    return text, recipe.get("image")

# ──────────────── حفظ في Excel ────────────────
def save_to_excel(recipe, user_id, username, youtube_link=""):
    row = {
        "التاريخ": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "العنوان": recipe.get("title"),
        "الدولة/المطبخ": recipe.get("cuisines", ["غير معروف"])[0] if recipe.get("cuisines") else "غير معروف",
        "الوقت": recipe.get("readyInMinutes"),
        "عدد الأشخاص": recipe.get("servings"),
        "المكونات": " • ".join([i["original"] for i in recipe.get("extendedIngredients", [])]),
        "الرابط": recipe.get("sourceUrl", ""),
        "يوتيوب": youtube_link,
        "User ID": user_id,
        "Username": username or "غير معروف"
    }
    saved_recipes.append(row)
    pd.DataFrame(saved_recipes).to_excel(EXCEL_FILE, index=False)

# ──────────────── البداية والأوامر ────────────────
@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "🌍 مرحباً في بوت الوصفات الشامل!\n"
        "اكتب أي وصفة تريدها (بالعربية أو الإنجليزية)\nمثال: كسكس، برجر، سوشي، فول مدمس...",
        reply_markup=main_keyboard()
    )

@router.message(lambda m: m.text == "🔍 بحث عن وصفة")
async def ask_for_recipe(message: types.Message):
    await message.answer("اكتب اسم الوصفة التي تريدها:")

@router.message()
async def search_handler(message: types.Message):
    query = message.text.strip()
    if query in ["📊 الوصفات المحفوظة"]:
        if os.path.exists(EXCEL_FILE):
            await message.answer_document(types.FSInputFile(EXCEL_FILE), caption="📊 جميع الوصفات المحفوظة")
        else:
            await message.answer("لا توجد وصفات محفوظة بعد.")
        return

    await message.answer("🔎 جاري البحث في الإنترنت ويوتيوب...")

    recipes, youtube_videos = await search_full_internet(query)

    if not recipes and not youtube_videos:
        await message.answer("لم أجد نتائج. جرب كتابة الاسم بطريقة أخرى.")
        return

    # عرض الوصفات
    for r in recipes[:5]:
        text, image = format_recipe(r)
        save_to_excel(r, message.from_user.id, message.from_user.username)
        await message.answer_photo(photo=image, caption=text)

    # عرض فيديوهات يوتيوب
    for v in youtube_videos:
        await message.answer(f"🎥 {v['title']}\n{v['channel']}\n{v['link']}")

    await message.answer("اكتب وصفة جديدة أو اضغط على الأزرار أدناه:", reply_markup=main_keyboard())

# ──────────────── Webhook Setup ────────────────
async def on_startup():
    await bot.delete_webhook(drop_pending_updates=True)
    webhook_url = f"https://{os.environ['RENDER_EXTERNAL_HOSTNAME']}/webhook"
    await bot.set_webhook(webhook_url)

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
