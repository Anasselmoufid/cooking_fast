#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت تيليغرام للبحث عن وصفات الطعام في يوتيوب
بدون استخدام API keys أو ذكاء اصطناعي
"""

import os
import re
import json
import urllib.request
import urllib.parse
from html import unescape
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

# ==================== الإعدادات ====================
TELEGRAM_TOKEN = "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"  # ضع توكن البوت هنا

# إعدادات البحث
MAX_RESULTS = 5

# تهيئة البوت
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# تخزين مؤقت لنتائج البحث
user_sessions = {}

# ==================== دالة البحث في يوتيوب بدون API ====================
def search_youtube(query):
    """البحث في يوتيوب باستخدام yt-dlp"""
    try:
        # إعدادات yt-dlp للبحث
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_generic_extractor': False,
        }
        
        # بحث في يوتيوب
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch{MAX_RESULTS}:{query} recipe"
            result = ydl.extract_info(search_query, download=False)
            
            videos = []
            if 'entries' in result:
                for entry in result['entries']:
                    video = {
                        'id': entry['id'],
                        'title': entry['title'],
                        'description': entry.get('description', 'لا يوجد وصف'),
                        'channel': entry.get('uploader', 'غير معروف'),
                        'duration': entry.get('duration_string', 'غير معروف'),
                        'views': entry.get('view_count', 0),
                        'thumbnail': entry.get('thumbnail', ''),
                        'url': f"https://youtube.com/watch?v={entry['id']}"
                    }
                    videos.append(video)
            
            return videos
            
    except Exception as e:
        print(f"خطأ في البحث: {e}")
        return []

def get_video_details(video_id):
    """الحصول على تفاصيل إضافية للفيديو"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://youtube.com/watch?v={video_id}", download=False)
            
            return {
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                'duration': info.get('duration_string', ''),
                'views': info.get('view_count', 0),
                'likes': info.get('like_count', 0),
                'channel': info.get('uploader', ''),
                'tags': info.get('tags', [])
            }
            
    except Exception as e:
        print(f"خطأ في جلب التفاصيل: {e}")
        return None

# ==================== دوال تحليل الوصفة بدون ذكاء اصطناعي ====================
def extract_ingredients(text):
    """استخراج المكونات من النص"""
    ingredients = []
    
    # كلمات مفتاحية للمكونات
    ingredient_keywords = [
        'مكونات', 'المقادير', 'ingredients', 'تحتاج', 'نحتاج',
        'كوب', 'ملعقة', 'كيلو', 'جرام', 'غرام', 'حبة', 'حبات'
    ]
    
    # تقسيم النص إلى سطور
    lines = text.split('\n')
    
    ingredient_section = False
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # التحقق إذا كان هذا السطر بداية قسم المكونات
        if any(keyword in line_lower for keyword in ['مكونات', 'المقادير', 'ingredients']):
            ingredient_section = True
            continue
        elif any(keyword in line_lower for keyword in ['طريقة', 'تحضير', 'instructions']):
            ingredient_section = False
            break
        
        # استخراج المكونات
        if ingredient_section and line and len(line) < 100:
            # التحقق من وجود أرقام أو مقادير
            if any(keyword in line_lower for keyword in ingredient_keywords) or re.search(r'\d+', line):
                clean_line = line.strip('•-*').strip()
                if clean_line and len(clean_line) > 3:
                    ingredients.append(clean_line)
    
    # إذا لم نجد مكونات، نبحث في كل النص
    if not ingredients:
        for line in lines[:20]:  # أول 20 سطر فقط
            if any(keyword in line.lower() for keyword in ingredient_keywords) or re.search(r'\d+\s*(كوب|ملعقة|جرام|غرام|حبة)', line):
                clean_line = line.strip('•-*').strip()
                if clean_line and len(clean_line) < 100:
                    ingredients.append(clean_line)
    
    return ingredients[:12]  # نرجع أول 12 مكون

def extract_instructions(text):
    """استخراج خطوات التحضير من النص"""
    instructions = []
    
    # كلمات مفتاحية للتحضير
    instruction_keywords = [
        'طريقة', 'تحضير', 'خطوات', 'instructions', 'direction',
        'اول', 'ثاني', 'ثالث', '1.', '2.', '3.', '-', '•'
    ]
    
    lines = text.split('\n')
    instruction_section = False
    temp_instructions = []
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # بداية قسم التحضير
        if any(keyword in line_lower for keyword in ['طريقة', 'تحضير', 'instructions']):
            instruction_section = True
            continue
        elif instruction_section and line and len(line) > 10:
            # تنظيف الخطوة
            step = line.strip('0123456789. •-').strip()
            if step and len(step) > 10 and step not in temp_instructions:
                temp_instructions.append(step)
        
        # نهاية القسم (عند العودة لمكونات أو معلومات أخرى)
        if instruction_section and 'مكونات' in line_lower:
            break
    
    # إذا لم نجد تعليمات، نبحث عن فقرات طويلة
    if not temp_instructions:
        for line in lines:
            if len(line) > 30 and not re.search(r'http|www|@', line):
                if 'مكونات' not in line.lower() and 'ingredients' not in line.lower():
                    temp_instructions.append(line.strip())
    
    return temp_instructions[:8]  # نرجع أول 8 خطوات

def extract_serving_tips(text):
    """استخراج نصائح التقديم"""
    serving_keywords = ['يقدم', 'تقديم', 'تزيين', 'بالهنا', 'بالشفا', 'serve', 'garnish']
    
    lines = text.split('\n')
    serving_tips = []
    
    for line in lines:
        if any(keyword in line.lower() for keyword in serving_keywords):
            serving_tips.append(line.strip())
    
    if serving_tips:
        return ' '.join(serving_tips[:2])  # نرجع أول نصيحتين
    
    return 'يقدم ساخناً بالهناء والشفاء'

def guess_country_from_title(title):
    """محاولة تخمين الدولة من العنوان"""
    countries = {
        'سعودي': 'المملكة العربية السعودية',
        'مصري': 'مصر',
        'شامي': 'سوريا/لبنان',
        'لبناني': 'لبنان',
        'سوري': 'سوريا',
        'عراقي': 'العراق',
        'مغربي': 'المغرب',
        'تونسي': 'تونس',
        'جزائري': 'الجزائر',
        'ليبي': 'ليبيا',
        'يمني': 'اليمن',
        'عماني': 'عمان',
        'اماراتي': 'الإمارات',
        'كويتي': 'الكويت',
        'قطري': 'قطر',
        'بحريني': 'البحرين',
        'تركي': 'تركيا',
        'هندي': 'الهند',
        'باكستاني': 'باكستان',
        'ايطالي': 'إيطاليا',
        'فرنسي': 'فرنسا',
        'صيني': 'الصين',
        'ياباني': 'اليابان',
        'تايلاندي': 'تايلاند',
        'مكسيكي': 'المكسيك',
        'امريكي': 'الولايات المتحدة'
    }
    
    title_lower = title.lower()
    for key, country in countries.items():
        if key in title_lower:
            return country
    
    return 'غير محدد'

def get_continent_from_country(country):
    """تحديد القارة بناءً على الدولة"""
    if country == 'غير محدد':
        return 'غير محدد'
    
    continents = {
        'آسيا': ['سعودي', 'مصري', 'شامي', 'لبناني', 'سوري', 'عراقي', 'يمني', 'عماني', 'اماراتي', 'كويتي', 'قطري', 'بحريني', 'تركي', 'هندي', 'باكستاني', 'صيني', 'ياباني', 'تايلاندي'],
        'أفريقيا': ['مغربي', 'تونسي', 'جزائري', 'ليبي', 'مصري'],
        'أوروبا': ['تركي', 'ايطالي', 'فرنسي'],
        'أمريكا الشمالية': ['مكسيكي', 'امريكي'],
        'أمريكا الجنوبية': [],
        'أستراليا': []
    }
    
    country_lower = country.lower()
    for continent, countries in continents.items():
        for c in countries:
            if c in country_lower:
                return continent
    
    return 'غير محدد'

def parse_recipe_info(title, description):
    """تحليل معلومات الوصفة"""
    
    # استخراج المكونات
    ingredients = extract_ingredients(description)
    if not ingredients:
        ingredients = extract_ingredients(title + " " + description[:500])
    
    # استخراج طريقة التحضير
    instructions = extract_instructions(description)
    if not instructions:
        instructions = ["شاهد الفيديو للتفاصيل الكامل"]
    
    # استخراج طريقة التقديم
    serving = extract_serving_tips(description)
    
    # تخمين الدولة
    country = guess_country_from_title(title)
    
    # تحديد القارة
    continent = get_continent_from_country(country)
    
    # اسم الوصفة (تنظيف العنوان)
    recipe_name = title
    # إزالة كلمات زائدة
    for word in ['وصفة', 'طريقة', 'عمل', 'تحضير', ' cooking', 'recipe', 'how to make']:
        recipe_name = recipe_name.replace(word, '')
    recipe_name = recipe_name.strip(' -:')
    
    return {
        'recipe_name': recipe_name,
        'country': country,
        'continent': continent,
        'ingredients': ingredients,
        'instructions': instructions,
        'serving': serving
    }

# ==================== دوال تنسيق الرد ====================
def format_recipe_response(video, recipe_info):
    """تنسيق الرد النهائي"""
    
    response = f"""
🍳 *{recipe_info['recipe_name']}*

📺 *القناة:* {video['channel']}
⏱️ *المدة:* {video['duration']}
👁️ *المشاهدات:* {video['views']:,}

"""
    
    # إضافة الدولة والقارة
    if recipe_info['country'] != 'غير محدد':
        response += f"🌍 *الدولة:* {recipe_info['country']}\n"
    if recipe_info['continent'] != 'غير محدد':
        response += f"🗺️ *القارة:* {recipe_info['continent']}\n"
    
    response += "\n"
    
    # المكونات
    if recipe_info['ingredients']:
        response += "📋 *المكونات:*\n"
        for ing in recipe_info['ingredients']:
            response += f"• {ing}\n"
        response += "\n"
    
    # طريقة التحضير
    if recipe_info['instructions']:
        response += "👩‍🍳 *طريقة التحضير:*\n"
        for i, step in enumerate(recipe_info['instructions'][:5], 1):
            if step.strip():
                response += f"{i}. {step}\n"
        response += "\n"
    
    # طريقة التقديم
    if recipe_info['serving']:
        response += f"🍽️ *طريقة التقديم:*\n{recipe_info['serving']}\n\n"
    
    # رابط الفيديو
    response += f"🔗 رابط الفيديو: {video['url']}"
    
    return response

# ==================== معالجات البوت ====================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """رسالة الترحيب"""
    welcome_text = """
👋 *مرحباً بك في بوت الوصفات!*

📝 *طريقة الاستخدام:*
أرسل لي اسم أي وصفة تبحث عنها، مثلاً:
• "بيتزا"
• "كبسة"
• "معكرونة"
• "باستا"

⚡ *مميزات البوت:*
• بحث مباشر في يوتيوب (بدون API)
• استخراج المكونات تلقائياً
• خطوات التحضير
• معلومات عن الدولة والقارة
• لا يحتاج أي مفاتيح API

🔧 *الأوامر المتاحة:*
/start - عرض رسالة الترحيب
/help - عرض المساعدة
    """
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def search_recipes(message):
    """البحث عن الوصفات"""
    chat_id = message.chat.id
    query = message.text
    
    # إرسال رسالة انتظار
    waiting_msg = bot.reply_to(message, "🔍 جاري البحث في يوتيوب...")
    
    # البحث في يوتيوب
    videos = search_youtube(query)
    
    if not videos:
        bot.edit_message_text(
            "😔 لم أجد نتائج. جرب كلمات بحث مختلفة.\n"
            "مثال: بيتزا, كبسة, معكرونة, باستا",
            chat_id,
            waiting_msg.message_id
        )
        return
    
    # تجهيز قائمة النتائج
    markup = InlineKeyboardMarkup(row_width=1)
    user_sessions[chat_id] = {'videos': videos}
    
    for i, video in enumerate(videos[:5]):
        # اختصار العنوان الطويل
        title = video['title'][:45] + '...' if len(video['title']) > 45 else video['title']
        btn_text = f"{i+1}. {title}"
        markup.add(InlineKeyboardButton(
            btn_text,
            callback_data=f"select_{i}"
        ))
    
    # تحديث رسالة الانتظار
    bot.edit_message_text(
        f"✅ تم العثور على {len(videos)} نتيجة. اختر أحدها:",
        chat_id,
        waiting_msg.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def handle_video_selection(call):
    """معالجة اختيار الفيديو"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    # استخراج رقم الفيديو المختار
    video_index = int(call.data.split('_')[1])
    video = user_sessions[chat_id]['videos'][video_index]
    
    # تحديث الرسالة
    bot.edit_message_text(
        f"📥 جاري تحميل معلومات الفيديو:\n{video['title']}\n\n⏳ يرجى الانتظار...",
        chat_id,
        message_id
    )
    
    # الحصول على تفاصيل الفيديو كاملة
    details = get_video_details(video['id'])
    
    if not details:
        bot.edit_message_text(
            "❌ حدث خطأ في تحميل تفاصيل الفيديو",
            chat_id,
            message_id
        )
        return
    
    # تحديث معلومات الفيديو
    video.update(details)
    
    # تحليل معلومات الوصفة
    recipe_info = parse_recipe_info(video['title'], video['description'])
    
    # تجهيز الرد
    response = format_recipe_response(video, recipe_info)
    
    # إرسال النتيجة
    bot.edit_message_text(
        response,
        chat_id,
        message_id,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    
    # إرسال صورة مصغرة إذا وجدت
    if video.get('thumbnail'):
        try:
            bot.send_photo(
                chat_id,
                video['thumbnail'],
                caption="🍽️ صورة من الفيديو"
            )
        except:
            pass

# ==================== تشغيل البوت ====================
if __name__ == '__main__':
    print("=" * 50)
    print("🤖 بوت الوصفات - بدون API Keys")
    print("=" * 50)
    print("\n✅ البوت يعمل...")
    print("📱 ابحث عن بوتك في تيليغرام وابدأ باستخدامه")
    print("\n❌ للخروج: Ctrl + C")
    print("=" * 50)
    
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("\n\n👋 تم إيقاف البوت")
    except Exception as e:
        print(f"\n❌ خطأ: {e}")
