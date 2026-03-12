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
TOKEN = os.environ.get("BOT_TOKEN") or "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"  # يفضل استخدام env var
SPOONACULAR_KEY = os.environ.get("SPOONACULAR_KEY") or "bd7328461e664336834eb1e43e82b248"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

EXCEL_FILE = "recipes.xlsx"
saved_recipes = []

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

async def search_spoonacular(query: str):
    if not SPOONACULAR_KEY or SPOONACULAR_KEY == "YOUR_SPOONACULAR_API_KEY":
        return [], "خطأ: مفتاح Spoonacular غير موجود أو غير صحيح"

    # بحث بالعربية + ترجمة إنجليزية تلقائية
    english_query = query
    try:
        from deep_translator import GoogleTranslator
        english_query = GoogleTranslator(source='ar', target='en').translate(query)
    except:
        pass

    url = f"https://api.spoonacular.com/recipes/complexSearch?query={english_query}&number=6&addRecipeInformation=true&apiKey={SPOONACULAR_KEY}"
    logging.info(f"جاري البحث في Spoonacular: {url}")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            logging.info(f"حالة الرد: {resp.status}")
            if resp.status != 200:
                text = await resp.text()
                logging.error(f"خطأ Spoonacular: {resp.status} - {text}")
                return [], f"خطأ من Spoonacular: حالة {resp.status}"
            data = await resp.json()
            results = data.get("results", [])
            logging.info(f"عدد النتائج: {len(results)}")
            return results, None

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

🔗 رابط: {recipe.get("sourceUrl", "غير متوفر")}
    """.strip()

    return text, recipe.get("image")

@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "🌍 مرحباً في بوت الوصفات الشامل!\n"
        "اكتب أي وصفة تريدها (بالعربية أو الإنجليزية)\nمثال: كسكس، برجر، سوشي، فول مدمس...",
        reply_markup=main_keyboard()
    )

@router.message()
async def search_handler(message: types.Message):
    query = message.text.strip()
    if query in ["📊 الوصفات المحفوظة"]:
        if os.path.exists(EXCEL_FILE):
            await message.answer_document(types.FSInputFile(EXCEL_FILE), caption="📊 جميع الوصفات المحفوظة")
        else:
            await message.answer("لا توجد وصفات محفوظة بعد.")
        return

    await message.answer(f"🔎 جاري البحث عن: {query}")

    results, error = await search_spoonacular(query)

    if error:
        await message.answer(error)
        return

    if not results:
        await message.answer("لم أجد نتائج. جرب كتابة الاسم بطريقة مختلفة أو بالإنجليزية.")
        return

    for r in results:
        text, image = format_recipe(r)
        await message.answer_photo(photo=image or "https://via.placeholder.com/512", caption=text)

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
