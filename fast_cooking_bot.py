# -*- coding: utf-8 -*-
import asyncio
import logging
import os
from datetime import datetime
from functools import lru_cache

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
TOKEN = "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"   # ← غيّر التوكن هنا
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

EXCEL_FILE = "recipes.xlsx"
recipes_cache = []

# الدول المتاحة + خريطة بسيطة (حسب ما في TheMealDB حالياً)
COUNTRIES = [
    "American", "British", "Canadian", "Chinese", "Croatian", "Dutch", "Egyptian",
    "French", "Greek", "Indian", "Irish", "Italian", "Jamaican", "Japanese",
    "Kenyan", "Malaysian", "Mexican", "Moroccan", "Russian", "Spanish",
    "Thai", "Tunisian", "Turkish", "Vietnamese", "Unknown"
]

# ──────────────── تخزين مؤقت للوصفات حسب الدولة ────────────────
country_meals_cache = {}  # country_name → list of meal dicts

@lru_cache(maxsize=1000)
def fast_translate(text: str, target: str = 'ar') -> str:
    if target == 'en' or not text:
        return text
    # هنا يمكنك إضافة ترجمة حقيقية لاحقاً
    # حالياً نتركها كما هي لأن معظم الوصفات بالإنجليزية
    return text

async def fetch_meals_by_country(session: aiohttp.ClientSession, country: str):
    if country in country_meals_cache:
        return country_meals_cache[country]

    url = f"https://www.themealdb.com/api/json/v1/1/filter.php?a={country}"
    async with session.get(url) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        meals = data.get("meals", [])
        country_meals_cache[country] = meals
        return meals

async def fetch_meal_details(session: aiohttp.ClientSession, meal_id: str):
    url = f"https://www.themealdb.com/api/json/v1/1/lookup.php?i={meal_id}"
    async with session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("meals", [None])[0]

def format_recipe(meal: dict, lang: str = 'ar') -> str:
    name = fast_translate(meal["strMeal"], lang)
    area = fast_translate(meal["strArea"], lang)
    category = fast_translate(meal.get("strCategory", "غير معروف"), lang)

    ingredients = []
    for i in range(1, 21):
        ing = meal.get(f"strIngredient{i}")
        mea = meal.get(f"strMeasure{i}")
        if ing and ing.strip() and ing.lower() != "null":
            line = f"{mea.strip()} {ing.strip()}" if mea and mea.strip() != "-" else ing.strip()
            ingredients.append(fast_translate(line, lang))

    raw_steps = [s.strip() for s in meal["strInstructions"].split('.') if len(s.strip()) > 10]
    steps = [f"{i+1}. {fast_translate(s, lang)}" for i, s in enumerate(raw_steps)]

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

def cache_recipe(user_id: int, username: str | None, meal: dict, lang: str):
    row = {
        "User ID": user_id,
        "Username": username or "غير معروف",
        "التاريخ": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "اسم الوصفة": meal["strMeal"],
        "الدولة": meal["strArea"],
        "التصنيف": meal.get("strCategory", "Unknown"),
        "المكونات": " • ".join([f"{meal.get(f'strMeasure{i}') or ''} {meal.get(f'strIngredient{i}') or ''}".strip() 
                                for i in range(1,21) if meal.get(f"strIngredient{i}")]),
        "الطريقة": meal["strInstructions"],
        "رابط الصورة": meal["strMealThumb"],
        "رابط يوتيوب": meal.get("strYoutube", ""),
    }
    recipes_cache.append(row)

def export_to_excel():
    if not recipes_cache:
        return False
    df = pd.DataFrame(recipes_cache)
    df.to_excel(EXCEL_FILE, index=False, engine='openpyxl')
    return True

# ──────────────── حالات ────────────────
class Form(StatesGroup):
    choosing_country = State()
    choosing_meal = State()
    searching = State()

# ──────────────── لوحة المفاتيح الرئيسية ────────────────
def get_main_keyboard(lang: str = 'ar') -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌍 اختر دولة" if lang=='ar' else "🌍 Choose Country")],
            [KeyboardButton(text="🍳 وصفة عشوائية" if lang=='ar' else "🍳 Random Recipe")],
            [KeyboardButton(text="📊 عرض المحفوظ" if lang=='ar' else "📊 Saved Recipes")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

# ──────────────── البداية ────────────────
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "مرحباً! اختر لغتك / Welcome! Choose language:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="العربية 🇸🇦"), KeyboardButton(text="English 🇬🇧")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

@router.message(lambda m: m.text in ["العربية 🇸🇦", "English 🇬🇧"])
async def set_language(message: types.Message):
    lang = 'ar' if "العربية" in message.text else 'en'
    user_id = str(message.from_user.id)
    user_languages[user_id] = lang

    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_languages, f, ensure_ascii=False, indent=2)

    await message.answer(
        "تم حفظ اللغة ✓\nاختر خياراً ↓" if lang=='ar' else "Language saved ✓\nChoose an option ↓",
        reply_markup=get_main_keyboard(lang)
    )

# ──────────────── اختيار الدولة ────────────────
@router.message(lambda m: "اختر دولة" in m.text or "Choose Country" in m.text)
async def show_countries(message: types.Message):
    lang = user_languages.get(str(message.from_user.id), 'ar')
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=c)] for c in COUNTRIES],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    await message.answer(
        "اختر الدولة:" if lang=='ar' else "Choose a country:",
        reply_markup=kb
    )

# ──────────────── عرض وصفات الدولة ────────────────
@router.message(lambda m: m.text in COUNTRIES)
async def show_country_meals(message: types.Message):
    lang = user_languages.get(str(message.from_user.id), 'ar')
    country = message.text

    await message.answer("جاري جلب الوصفات... ⏳")

    async with aiohttp.ClientSession() as session:
        meals = await fetch_meals_by_country(session, country)

        if not meals:
            await message.answer(
                f"لا توجد وصفات متاحة لهذه الدولة حالياً ({country})",
                reply_markup=get_main_keyboard(lang)
            )
            return

        # عرض أول 12 وصفة فقط (لعدم الإغراق)
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=m["strMeal"])] for m in meals[:12]],
            resize_keyboard=True,
            one_time_keyboard=False
        )

        await message.answer(
            f"وصفات متاحة من {country} ({len(meals)} وصفة):",
            reply_markup=kb
        )

# ──────────────── عرض تفاصيل وصفة محددة ────────────────
@router.message()
async def handle_meal_name(message: types.Message):
    lang = user_languages.get(str(message.from_user.id), 'ar')
    meal_name = message.text.strip()

    if meal_name in ["📊 عرض المحفوظ", "📊 Saved Recipes"]:
        if export_to_excel():
            await message.answer_document(FSInputFile(EXCEL_FILE),
                                          caption="ملف الوصفات المحفوظة")
        else:
            await message.answer("لا توجد وصفات محفوظة بعد.")
        return

    if meal_name in ["🍳 وصفة عشوائية", "🍳 Random Recipe"]:
        await random_recipe(message)
        return

    # باقي النصوص → نفترض إنها اسم وصفة
    await message.answer("جاري جلب تفاصيل الوصفة... ⏳")

    async with aiohttp.ClientSession() as session:
        # بحث عن الوصفة بالاسم
        meal = await fetch_recipe(session, meal_name)
        if not meal:
            await message.answer("لم أجد وصفة بهذا الاسم بالضبط، جرب اختيار من القائمة أو اكتب اسم آخر.")
            return

        text, photo_url, _ = format_recipe(meal, lang)
        cache_recipe(message.from_user.id, message.from_user.username, meal, lang)

        await message.answer_photo(photo=photo_url, caption=text)
        await message.answer("اختر خياراً ↓", reply_markup=get_main_keyboard(lang))

# ──────────────── وصفة عشوائية ────────────────
async def random_recipe(message: types.Message):
    lang = user_languages.get(str(message.from_user.id), 'ar')
    await message.answer("جاري جلب وصفة عشوائية... ⏳")

    async with aiohttp.ClientSession() as session:
        meal = await fetch_recipe(session)
        if not meal:
            await message.answer("حدث خطأ، جرب مرة أخرى.")
            return

        text, photo_url, raw_meal = format_recipe(meal, lang)
        cache_recipe(message.from_user.id, message.from_user.username, raw_meal, lang)

        await message.answer_photo(photo=photo_url, caption=text)
        await message.answer("اختر خياراً ↓", reply_markup=get_main_keyboard(lang))

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
