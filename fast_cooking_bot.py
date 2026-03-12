import asyncio
import logging
from datetime import datetime
import json
import os
from functools import lru_cache

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import aiohttp
from deep_translator import GoogleTranslator
import pandas as pd

# ──────────────── إعدادات ────────────────
TOKEN = "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"  # غيّره هنا
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

USERS_FILE = "users_lang.json"
EXCEL_FILE = "recipes.xlsx"
recipes_cache = []  # تخزين مؤقت للوصفات (للسرعة)

LANGUAGES = {
    'ar': '🇸🇦 العربية',
    'en': '🇬🇧 English',
    'es': '🇪🇸 Español',
    'fr': '🇫🇷 Français',
    'de': '🇩🇪 Deutsch'
}

CONTINENT_MAP = {
    "Egyptian": "Africa", "Moroccan": "Africa", "Italian": "Europe",
    # ... أكمل باقي الخريطة إذا أردت
}

# ──────────────── ترجمة مع cache قوي ────────────────
@lru_cache(maxsize=1000)
def fast_translate(text: str, target: str) -> str:
    if target == 'en' or not text:
        return text
    try:
        return GoogleTranslator(source='en', target=target).translate(text)
    except:
        return text

# ──────────────── جلب وصفة (async) ────────────────
async def fetch_recipe(session: aiohttp.ClientSession, query: str = None):
    if query:
        url = f"https://www.themealdb.com/api/json/v1/1/search.php?s={query}"
    else:
        url = "https://www.themealdb.com/api/json/v1/1/random.php"
    
    async with session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("meals", [None])[0]

# ──────────────── تنسيق الرسالة (مراحل مرقمة + تفاصيل) ────────────────
def format_recipe(meal: dict, lang: str) -> tuple[str, str]:
    name = fast_translate(meal["strMeal"], lang)
    area = fast_translate(meal["strArea"], lang)
    continent = fast_translate(CONTINENT_MAP.get(meal["strArea"], "World"), lang)
    category = fast_translate(meal.get("strCategory", "Unknown"), lang)

    # مكونات
    ingredients = []
    for i in range(1, 21):
        ing = meal.get(f"strIngredient{i}")
        mea = meal.get(f"strMeasure{i}")
        if ing and ing.strip() and ing.lower() != "null":
            line = f"{mea.strip()} {ing.strip()}" if mea and mea.strip() != "-" else ing.strip()
            ingredients.append(fast_translate(line, lang))

    # مراحل مرقمة تفصيلية
    raw_steps = [s.strip() for s in meal["strInstructions"].split('.') if len(s.strip()) > 10]
    steps = [f"{i+1}. {fast_translate(s, lang)}" for i, s in enumerate(raw_steps)]

    text = f"""
🍽 **{name}**

🏳️ الدولة: {area}
🌍 القارة: {continent}
📌 التصنيف: {category}

📋 المكونات ({len(ingredients)}):
• {'\n• '.join(ingredients)}

🔢 طريقة التحضير ({len(steps)} خطوة):
{"\n".join(steps)}

📹 فيديو: {meal.get("strYoutube", "غير متوفر")}
    """.strip()

    return text, meal["strMealThumb"]

# ──────────────── حفظ في الذاكرة (سريع) ────────────────
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

# ──────────────── كتابة Excel عند الطلب فقط ────────────────
def export_to_excel():
    if not recipes_cache:
        return False
    df = pd.DataFrame(recipes_cache)
    df.to_excel(EXCEL_FILE, index=False, engine='openpyxl')
    return True

# ──────────────── حالات FSM للبحث ────────────────
class SearchForm(StatesGroup):
    waiting_for_query = State()

# ──────────────── أوامر وبوت ────────────────
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=v, callback_data=f"setlang_{k}")] for k, v in LANGUAGES.items()
    ])
    await message.answer("🌍 اختر لغتك المفضلة / Choose your language:", reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith("setlang_"))
async def set_language(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_id = str(callback.from_user.id)
    user_languages[user_id] = lang
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_languages, f, ensure_ascii=False, indent=2)

    await callback.message.edit_text("✅ تم حفظ اللغة!", reply_markup=None)
    await show_main_menu(callback.message, lang)
    await callback.answer()

async def show_main_menu(message_or_call, lang: str):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍳 وصفة عشوائية" if lang=='ar' else "🍳 Random", callback_data="random")],
        [InlineKeyboardButton(text="🔍 بحث عن وصفة" if lang=='ar' else "🔍 Search", callback_data="search")],
    ])
    text = "اختر خياراً ↓" if lang=='ar' else "Choose an option ↓"
    if isinstance(message_or_call, types.Message):
        await message_or_call.answer(text, reply_markup=kb)
    else:
        await message_or_call.edit_text(text, reply_markup=kb)

@router.callback_query(lambda c: c.data == "random")
async def random_recipe(callback: types.CallbackQuery):
    lang = user_languages.get(str(callback.from_user.id), 'ar')
    async with aiohttp.ClientSession() as session:
        meal = await fetch_recipe(session)
        if not meal:
            await callback.answer("خطأ في جلب الوصفة", show_alert=True)
            return

        text, photo_url = format_recipe(meal, lang)
        cache_recipe(callback.from_user.id, callback.from_user.username, meal, lang)

        await callback.message.answer_photo(photo=photo_url, caption=text, parse_mode="Markdown")
        await callback.answer("تم الحفظ في الذاكرة ✓")

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

    # ترجمة الاستعلام إلى الإنجليزية إذا لزم
    if lang != 'en':
        query = fast_translate(query, 'en')

    async with aiohttp.ClientSession() as session:
        meal = await fetch_recipe(session, query)
        if not meal:
            await message.answer("❌ لم أجد وصفة بهذا الاسم، جرب اسم آخر.")
            await state.clear()
            return

        text, photo_url = format_recipe(meal, lang)
        cache_recipe(message.from_user.id, message.from_user.username, meal, lang)

        await message.answer_photo(photo=photo_url, caption=text, parse_mode="Markdown")
        await state.clear()

@router.message(Command("recipes", "وصفات"))
async def cmd_recipes(message: types.Message):
    if export_to_excel():
        await message.answer_document(document=FSInputFile(EXCEL_FILE),
                                      caption="📊 ملف الوصفات الكامل (مفصل جداً)")
    else:
        await message.answer("لا توجد وصفات محفوظة بعد.")

# ──────────────── التشغيل ────────────────
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())