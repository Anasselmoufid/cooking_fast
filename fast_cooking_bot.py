import asyncio
import logging
import os
import json
from datetime import datetime
from functools import lru_cache

import aiohttp
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from deep_translator import GoogleTranslator
import pandas as pd

# ──────────────── إعدادات ────────────────
TOKEN = "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"   # ← غيّر التوكن هنا
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

USERS_FILE = "users_lang.json"
EXCEL_FILE = "recipes.xlsx"
recipes_cache = []

user_languages = {}
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        user_languages = json.load(f)

LANGUAGES = {
    'ar': '🇸🇦 العربية',
    'en': '🇬🇧 English',
    'es': '🇪🇸 Español',
    'fr': '🇫🇷 Français',
    'de': '🇩🇪 Deutsch'
}

CONTINENT_MAP = {
    "Egyptian": "Africa", "Moroccan": "Africa", "Tunisian": "Africa",
    "Saudi Arabian": "Asia", "Syrian": "Asia", "Turkish": "Asia",
    "Italian": "Europe", "British": "Europe", "French": "Europe",
    "American": "North America", "Mexican": "North America",
}

@lru_cache(maxsize=1000)
def fast_translate(text: str, target: str) -> str:
    if target == 'en' or not text:
        return text
    try:
        return GoogleTranslator(source='en', target=target).translate(text)
    except:
        return text

async def fetch_recipe(session: aiohttp.ClientSession, query: str = None):
    url = "https://www.themealdb.com/api/json/v1/1/random.php" if not query else \
          f"https://www.themealdb.com/api/json/v1/1/search.php?s={query}"
    async with session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("meals", [None])[0]

def format_recipe(meal: dict, lang: str) -> tuple:
    name = fast_translate(meal["strMeal"], lang)
    area = fast_translate(meal["strArea"], lang)
    continent = fast_translate(CONTINENT_MAP.get(meal["strArea"], "World"), lang)
    category = fast_translate(meal.get("strCategory", "Unknown"), lang)

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
🌍 القارة: {continent}
📌 التصنيف: {category}

📋 المكونات ({len(ingredients)}):
• {'\n• '.join(ingredients)}

🔢 طريقة التحضير ({len(steps)} خطوة):
{"\n".join(steps)}

📹 فيديو: {meal.get("strYoutube", "غير متوفر")}
    """.strip()

    return text, meal["strMealThumb"], meal

def cache_recipe(user_id: int, username: str | None, meal: dict, lang: str):
    row = {
        "User ID": user_id,
        "Username": username or "غير معروف",
        "التاريخ": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "اسم الوصفة (EN)": meal["strMeal"],
        "اسم الوصفة": fast_translate(meal["strMeal"], lang),
        "الدولة": meal["strArea"],
        "القارة": CONTINENT_MAP.get(meal["strArea"], "World"),
        "التصنيف": meal.get("strCategory", "Unknown"),
        "عدد المكونات": sum(1 for i in range(1,21) if meal.get(f"strIngredient{i}")),
        "المكونات": " • ".join([f"{meal.get(f'strMeasure{i}') or ''} {meal.get(f'strIngredient{i}') or ''}".strip() 
                                for i in range(1,21) if meal.get(f"strIngredient{i}")]),
        "عدد الخطوات": len([s for s in meal["strInstructions"].split('.') if len(s.strip()) > 10]),
        "الطريقة الكاملة": meal["strInstructions"],
        "رابط يوتيوب": meal.get("strYoutube", ""),
        "رابط المصدر": meal.get("strSource", ""),
        "رابط الصورة": meal["strMealThumb"],
        "اللغة": lang
    }
    recipes_cache.append(row)

def export_to_excel():
    if not recipes_cache:
        return False
    df = pd.DataFrame(recipes_cache)
    df.to_excel(EXCEL_FILE, index=False, engine='openpyxl')
    return True

class SearchForm(StatesGroup):
    waiting_for_query = State()

# ──────────────── القوائم ────────────────
def get_main_menu(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍳 وصفة عشوائية" if lang=='ar' else "🍳 Random Recipe", callback_data="random")],
        [InlineKeyboardButton(text="🔍 بحث عن وصفة" if lang=='ar' else "🔍 Search Recipe", callback_data="search")],
        [InlineKeyboardButton(text="🔄 ابدأ من جديد" if lang=='ar' else "🔄 Start Over", callback_data="restart")],
    ])
    return kb

async def show_main_menu(message_or_call, lang: str):
    kb = get_main_menu(lang)
    text = "اختر خياراً ↓" if lang=='ar' else "Choose an option ↓"
    if isinstance(message_or_call, types.Message):
        await message_or_call.answer(text, reply_markup=kb)
    else:
        await message_or_call.message.edit_text(text, reply_markup=kb)

# ──────────────── الأوامر والأزرار ────────────────
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=v, callback_data=f"setlang_{k}")] for k, v in LANGUAGES.items()
    ])
    await message.answer("🌍 اختر لغتك المفضلة / Choose your language:", reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith("setlang_"))
async def set_language(callback: types.CallbackQuery):
    global user_languages

    lang = callback.data.split("_")[1]
    user_id = str(callback.from_user.id)
    user_languages[user_id] = lang

    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_languages, f, ensure_ascii=False, indent=2)

    await callback.message.edit_text("✅ تم حفظ اللغة!", reply_markup=None)
    await show_main_menu(callback, lang)
    await callback.answer()

@router.callback_query(lambda c: c.data == "restart")
async def restart(callback: types.CallbackQuery):
    lang = user_languages.get(str(callback.from_user.id), 'ar')
    await show_main_menu(callback, lang)
    await callback.answer("تم العودة للقائمة الرئيسية ✓")

@router.callback_query(lambda c: c.data == "random")
async def random_recipe(callback: types.CallbackQuery):
    lang = user_languages.get(str(callback.from_user.id), 'ar')
    async with aiohttp.ClientSession() as session:
        meal = await fetch_recipe(session)
        if not meal:
            await callback.answer("خطأ في جلب الوصفة", show_alert=True)
            return

        text, photo_url, raw_meal = format_recipe(meal, lang)
        cache_recipe(callback.from_user.id, callback.from_user.username, raw_meal, lang)

        await callback.message.answer_photo(photo=photo_url, caption=text)
        # العودة للقائمة الرئيسية تلقائيًا
        await show_main_menu(callback, lang)
        await callback.answer("تم الحفظ ✓")

@router.callback_query(lambda c: c.data == "search")
async def start_search(callback: types.CallbackQuery, state: FSMContext):
    lang = user_languages.get(str(callback.from_user.id), 'ar')
    text = "اكتب اسم الطبق (بالعربية أو الإنجليزية):" if lang=='ar' else "Type the dish name:"
    await callback.message.answer(text)
    await state.set_state(SearchForm.waiting_for_query)
    await callback.answer()

@router.message(SearchForm.waiting_for_query)
async def process_search(message: types.Message, state: FSMContext):
    lang = user_languages.get(str(message.from_user.id), 'ar')
    query = message.text.strip()

    if lang != 'en':
        query = fast_translate(query, 'en')

    async with aiohttp.ClientSession() as session:
        meal = await fetch_recipe(session, query)
        if not meal:
            await message.answer("❌ لم أجد وصفة بهذا الاسم، جرب اسم آخر.")
            await state.clear()
            await show_main_menu(message, lang)  # عودة للقائمة
            return

        text, photo_url, raw_meal = format_recipe(meal, lang)
        cache_recipe(message.from_user.id, message.from_user.username, raw_meal, lang)

        await message.answer_photo(photo=photo_url, caption=text)
        await state.clear()
        await show_main_menu(message, lang)  # عودة للقائمة بعد الوصفة

@router.message(Command("recipes", "وصفات"))
async def cmd_recipes(message: types.Message):
    if export_to_excel():
        await message.answer_document(document=FSInputFile(EXCEL_FILE),
                                      caption="📊 ملف الوصفات الكامل (مفصل جداً)")
    else:
        await message.answer("لا توجد وصفات محفوظة بعد.")

# ──────────────── Webhook + Startup ────────────────
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
