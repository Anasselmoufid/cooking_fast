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

# ──────────────── إعدادات ────────────────
TOKEN = "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"   # ← غيّر التوكن هنا
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# اللغات فقط عربي وإنجليزي
LANGUAGES = {
    'ar': 'العربية 🇸🇦',
    'en': 'English 🇬🇧'
}

# قائمة الدول المتاحة في TheMealDB
COUNTRIES = [
    "American", "British", "Canadian", "Chinese", "Croatian", "Dutch", "Egyptian",
    "French", "Greek", "Indian", "Irish", "Italian", "Jamaican", "Japanese",
    "Kenyan", "Malaysian", "Mexican", "Moroccan", "Russian", "Spanish",
    "Thai", "Tunisian", "Turkish", "Vietnamese", "Unknown"
]

# ──────────────── لوحة الدول الدائمة تحت خانة الكتابة ────────────────
def get_countries_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=country)] for country in COUNTRIES],
        resize_keyboard=True,
        one_time_keyboard=False,  # تبقى ظاهرة دائمًا
        input_field_placeholder="اختر دولة..."
    )

# ──────────────── جلب وصفات الدولة ────────────────
async def fetch_meals_by_country(session: aiohttp.ClientSession, country: str):
    url = f"https://www.themealdb.com/api/json/v1/1/filter.php?a={country}"
    async with session.get(url) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data.get("meals", [])

# ──────────────── جلب تفاصيل وصفة معينة ────────────────
async def fetch_meal_details(session: aiohttp.ClientSession, meal_id: str):
    url = f"https://www.themealdb.com/api/json/v1/1/lookup.php?i={meal_id}"
    async with session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("meals", [None])[0]

# ──────────────── تنسيق الوصفة (بدون parse_mode لتجنب الأخطاء) ────────────────
def format_recipe(meal: dict, lang: str = 'ar') -> str:
    name = meal["strMeal"]
    area = meal["strArea"]
    category = meal.get("strCategory", "غير معروف")

    ingredients = []
    for i in range(1, 21):
        ing = meal.get(f"strIngredient{i}")
        mea = meal.get(f"strMeasure{i}")
        if ing and ing.strip() and ing.lower() != "null":
            line = f"{mea.strip()} {ing.strip()}" if mea and mea.strip() != "-" else ing.strip()
            ingredients.append(line)

    raw_steps = [s.strip() for s in meal["strInstructions"].split('.') if len(s.strip()) > 10]
    steps = [f"{i+1}. {s}" for i, s in enumerate(raw_steps)]

    text = f"""
🍽 {name}

🏳️ الدولة: {area}
📌 التصنيف: {category}

📋 المكونات ({len(ingredients)}):
• {'\n• '.join(ingredients)}

🔢 طريقة التحضير ({len(steps)} خطوة):
{"\n".join(steps)}

📹 فيديو: {meal.get("strYoutube", "غير متوفر")}
    """.strip()

    return text

# ──────────────── البداية ────────────────
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=LANGUAGES['ar']), KeyboardButton(text=LANGUAGES['en'])]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "مرحباً! اختر لغتك:\n\nWelcome! Choose your language:",
        reply_markup=kb
    )

# ──────────────── حفظ اللغة وعرض قائمة الدول مباشرة ودائمة ────────────────
@router.message(lambda message: message.text in [LANGUAGES['ar'], LANGUAGES['en']])
async def set_language_and_show_countries(message: types.Message):
    lang = 'ar' if message.text == LANGUAGES['ar'] else 'en'

    # حفظ اللغة (اختياري)
    user_id = str(message.from_user.id)
    with open("users_lang.json", "w", encoding="utf-8") as f:
        json.dump({user_id: lang}, f, ensure_ascii=False)

    await message.answer(
        "تم اختيار اللغة ✓\nاختر دولة من القائمة أدناه:" if lang == 'ar' else
        "Language selected ✓\nChoose a country from the menu below:",
        reply_markup=get_countries_keyboard()
    )

# ──────────────── عند الضغط على دولة من القائمة ────────────────
@router.message(lambda message: message.text in COUNTRIES)
async def handle_country_selection(message: types.Message):
    country = message.text
    await message.answer(f"جاري جلب وصفات {country}... ⏳")

    async with aiohttp.ClientSession() as session:
        meals = await fetch_meals_by_country(session, country)

        if not meals:
            await message.answer(
                f"لا توجد وصفات متاحة حاليًا من {country}.",
                reply_markup=get_countries_keyboard()
            )
            return

        # عرض أسماء الوصفات كأزرار (حد أقصى 12 لتجنب الإغراق)
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=m["strMeal"])] for m in meals[:12]],
            resize_keyboard=True,
            one_time_keyboard=False
        )

        await message.answer(
            f"وصفات متاحة من {country} ({len(meals)} وصفة):",
            reply_markup=kb
        )

# ──────────────── عرض تفاصيل الوصفة عند الضغط على اسمها ────────────────
@router.message()
async def handle_meal_selection(message: types.Message):
    meal_name = message.text.strip()

    await message.answer(f"جاري جلب تفاصيل {meal_name}... ⏳")

    async with aiohttp.ClientSession() as session:
        url = f"https://www.themealdb.com/api/json/v1/1/search.php?s={meal_name}"
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                meal = data.get("meals", [None])[0]
                if meal:
                    text = format_recipe(meal)
                    await message.answer_photo(photo=meal["strMealThumb"], caption=text)
                    await message.answer("اختر دولة أخرى أو وصفة أخرى:", reply_markup=get_countries_keyboard())
                else:
                    await message.answer("لم أجد وصفة بهذا الاسم بالضبط.")
            else:
                await message.answer("حدث خطأ في الاتصال، جرب مرة أخرى.")

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
    print(f"Server running on port {os.environ.get('PORT', 10000)}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
