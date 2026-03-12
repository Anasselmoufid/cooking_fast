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

# ──────────────── إعدادات ────────────────
TOKEN = "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"                     # ← توكن البوت
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

# ──────────────── بحث شامل باستخدام Spoonacular (الإنترنت كامل) ────────────────
async def search_spoonacular(query: str):
    url = f"https://api.spoonacular.com/recipes/complexSearch?query={query}&number=8&addRecipeInformation=true&apiKey={SPOONACULAR_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("results", [])

# ──────────────── تنسيق الوصفة ────────────────
def format_recipe(recipe):
    title = recipe.get("title", "غير معروف")
    ready = recipe.get("readyInMinutes", "?")
    servings = recipe.get("servings", "?")
    source = recipe.get("sourceUrl", "")

    ingredients = [ing["original"] for ing in recipe.get("extendedIngredients", [])]

    text = f"""
🍽 **{title}**

⏱ وقت التحضير: {ready} دقيقة
👥 عدد الأشخاص: {servings}

📋 المكونات:
• {'\n• '.join(ingredients[:15])}

🔗 المصدر: {source}
    """.strip()

    image = recipe.get("image")
    return text, image

# ──────────────── حفظ في Excel ────────────────
def save_recipe(recipe, user_id, username):
    row = {
        "التاريخ": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "العنوان": recipe.get("title"),
        "الوقت": recipe.get("readyInMinutes"),
        "الصورة": recipe.get("image"),
        "الرابط": recipe.get("sourceUrl"),
        "User ID": user_id,
        "Username": username or "غير معروف"
    }
    saved_recipes.append(row)
    pd.DataFrame(saved_recipes).to_excel(EXCEL_FILE, index=False)

# ──────────────── البداية ────────────────
@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "مرحباً بك في بوت الوصفات الشامل 🌍\n"
        "اكتب اسم أي وصفة تريدها (بالعربية أو الإنجليزية)",
        reply_markup=main_keyboard()
    )

@router.message(lambda m: m.text == "🔍 بحث عن وصفة")
async def ask_search(message: types.Message):
    await message.answer("اكتب اسم الوصفة التي تبحث عنها:")

@router.message()
async def handle_any_message(message: types.Message):
    query = message.text.strip()
    if query in ["📊 الوصفات المحفوظة", "🍳 وصفة عشوائية"]:
        await message.answer("هذه الميزة قيد التطوير...")
        return

    await message.answer("🔎 جاري البحث في الإنترنت كاملاً...")

    results = await search_spoonacular(query)

    if not results:
        await message.answer("لم أجد نتائج. جرب كتابة الاسم بطريقة مختلفة.")
        return

    for r in results:
        text, image = format_recipe(r)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="فتح الوصفة كاملة", url=r.get("sourceUrl", "#"))]
        ])
        await message.answer_photo(photo=image, caption=text, reply_markup=kb)

    await message.answer("اكتب وصفة جديدة أو اختر من الأزرار أدناه:", reply_markup=main_keyboard())

# ──────────────── Webhook ────────────────
async def on_startup():
    await bot.delete_webhook(drop_pending_updates=True)
    webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/webhook"
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
