#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت تيليغرام للبحث عن وصفات الطعام - نسخة Webhook لـ Render
مدمج بالكامل وجاهز للتشغيل
"""

import os
import re
import json
import time
import requests
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

# ==================== الإعدادات الأساسية ====================
TELEGRAM_TOKEN = "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ"
RENDER_URL = "https://cooking-fast-1.onrender.com"
MAX_RESULTS = 5

# تهيئة البوت
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# تهيئة Flask
app = Flask(__name__)

# تخزين مؤقت لنتائج البحث
user_sessions = {}

# ==================== دوال البحث في يوتيوب ====================
def search_youtube(query):
    """البحث في يوتيوب باستخدام yt-dlp"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_generic_extractor': False,
        }
        
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

# ==================== دوال تحليل الوصفة ====================
def extract_ingredients(text):
    """استخراج المكونات من النص"""
    ingredients = []
    
    ingredient_keywords = [
        'مكونات', 'المقادير', 'ingredients', 'تحتاج', 'نحتاج',
        'كوب', 'ملعقة', 'كيلو', 'جرام', 'غرام', 'حبة', 'حبات'
    ]
    
    lines = text.split('\n')
    ingredient_section = False
    
    for line in lines:
        line_lower = line.lower().strip()
        
        if any(keyword in line_lower for keyword in ['مكونات', 'المقادير', 'ingredients']):
            ingredient_section = True
            continue
        elif any(keyword in line_lower for keyword in ['طريقة', 'تحضير', 'instructions']):
            ingredient_section = False
            break
        
        if ingredient_section and line and len(line) < 100:
            if any(keyword in line_lower for keyword in ingredient_keywords) or re.search(r'\d+', line):
                clean_line = line.strip('•-*').strip()
                if clean_line and len(clean_line) > 3:
                    ingredients.append(clean_line)
    
    if not ingredients:
        for line in lines[:20]:
            if any(keyword in line.lower() for keyword in ingredient_keywords) or re.search(r'\d+\s*(كوب|ملعقة|جرام|غرام|حبة)', line):
                clean_line = line.strip('•-*').strip()
                if clean_line and len(clean_line) < 100:
                    ingredients.append(clean_line)
    
    return ingredients[:12]

def extract_instructions(text):
    """استخراج خطوات التحضير من النص"""
    instructions = []
    
    instruction_keywords = [
        'طريقة', 'تحضير', 'خطوات', 'instructions', 'direction',
        'اول', 'ثاني', 'ثالث', '1.', '2.', '3.', '-', '•'
    ]
    
    lines = text.split('\n')
    instruction_section = False
    temp_instructions = []
    
    for line in lines:
        line_lower = line.lower().strip()
        
        if any(keyword in line_lower for keyword in ['طريقة', 'تحضير', 'instructions']):
            instruction_section = True
            continue
        elif instruction_section and line and len(line) > 10:
            step = line.strip('0123456789. •-').strip()
            if step and len(step) > 10 and step not in temp_instructions:
                temp_instructions.append(step)
        
        if instruction_section and 'مكونات' in line_lower:
            break
    
    if not temp_instructions:
        for line in lines:
            if len(line) > 30 and not re.search(r'http|www|@', line):
                if 'مكونات' not in line.lower() and 'ingredients' not in line.lower():
                    temp_instructions.append(line.strip())
    
    return temp_instructions[:8]

def extract_serving_tips(text):
    """استخراج نصائح التقديم"""
    serving_keywords = ['يقدم', 'تقديم', 'تزيين', 'بالهنا', 'بالشفا', 'serve', 'garnish']
    
    lines = text.split('\n')
    serving_tips = []
    
    for line in lines:
        if any(keyword in line.lower() for keyword in serving_keywords):
            serving_tips.append(line.strip())
    
    if serving_tips:
        return ' '.join(serving_tips[:2])
    
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
    
    country_lower = country.lower()
    
    asia = ['سعودي', 'مصري', 'شامي', 'لبناني', 'سوري', 'عراقي', 'يمني', 'عماني', 'اماراتي', 'كويتي', 'قطري', 'بحريني', 'تركي', 'هندي', 'باكستاني', 'صيني', 'ياباني', 'تايلاندي']
    africa = ['مغربي', 'تونسي', 'جزائري', 'ليبي', 'مصري']
    europe = ['تركي', 'ايطالي', 'فرنسي']
    north_america = ['مكسيكي', 'امريكي']
    
    for c in asia:
        if c in country_lower:
            return 'آسيا'
    for c in africa:
        if c in country_lower:
            return 'أفريقيا'
    for c in europe:
        if c in country_lower:
            return 'أوروبا'
    for c in north_america:
        if c in country_lower:
            return 'أمريكا الشمالية'
    
    return 'غير محدد'

def parse_recipe_info(title, description):
    """تحليل معلومات الوصفة"""
    
    ingredients = extract_ingredients(description)
    if not ingredients:
        ingredients = extract_ingredients(title + " " + description[:500])
    
    instructions = extract_instructions(description)
    if not instructions:
        instructions = ["شاهد الفيديو للتفاصيل الكاملة"]
    
    serving = extract_serving_tips(description)
    country = guess_country_from_title(title)
    continent = get_continent_from_country(country)
    
    recipe_name = title
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

def format_recipe_response(video, recipe_info):
    """تنسيق الرد النهائي"""
    
    response = f"""
🍳 *{recipe_info['recipe_name']}*

📺 *القناة:* {video['channel']}
⏱️ *المدة:* {video['duration']}
👁️ *المشاهدات:* {video['views']:,}

"""
    
    if recipe_info['country'] != 'غير محدد':
        response += f"🌍 *الدولة:* {recipe_info['country']}\n"
    if recipe_info['continent'] != 'غير محدد':
        response += f"🗺️ *القارة:* {recipe_info['continent']}\n"
    
    response += "\n"
    
    if recipe_info['ingredients']:
        response += "📋 *المكونات:*\n"
        for ing in recipe_info['ingredients']:
            response += f"• {ing}\n"
        response += "\n"
    
    if recipe_info['instructions']:
        response += "👩‍🍳 *طريقة التحضير:*\n"
        for i, step in enumerate(recipe_info['instructions'][:5], 1):
            if step.strip():
                response += f"{i}. {step}\n"
        response += "\n"
    
    if recipe_info['serving']:
        response += f"🍽️ *طريقة التقديم:*\n{recipe_info['serving']}\n\n"
    
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
• بحث مباشر في يوتيوب
• استخراج المكونات تلقائياً
• خطوات التحضير
• معلومات عن الدولة والقارة

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
    
    waiting_msg = bot.reply_to(message, "🔍 جاري البحث في يوتيوب...")
    
    videos = search_youtube(query)
    
    if not videos:
        bot.edit_message_text(
            "😔 لم أجد نتائج. جرب كلمات بحث مختلفة.\n"
            "مثال: بيتزا, كبسة, معكرونة, باستا",
            chat_id,
            waiting_msg.message_id
        )
        return
    
    markup = InlineKeyboardMarkup(row_width=1)
    user_sessions[chat_id] = {'videos': videos}
    
    for i, video in enumerate(videos[:5]):
        title = video['title'][:45] + '...' if len(video['title']) > 45 else video['title']
        btn_text = f"{i+1}. {title}"
        markup.add(InlineKeyboardButton(
            btn_text,
            callback_data=f"select_{i}"
        ))
    
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
    
    video_index = int(call.data.split('_')[1])
    video = user_sessions[chat_id]['videos'][video_index]
    
    bot.edit_message_text(
        f"📥 جاري تحميل معلومات الفيديو:\n{video['title']}\n\n⏳ يرجى الانتظار...",
        chat_id,
        message_id
    )
    
    details = get_video_details(video['id'])
    
    if not details:
        bot.edit_message_text(
            "❌ حدث خطأ في تحميل تفاصيل الفيديو",
            chat_id,
            message_id
        )
        return
    
    video.update(details)
    recipe_info = parse_recipe_info(video['title'], video['description'])
    response = format_recipe_response(video, recipe_info)
    
    bot.edit_message_text(
        response,
        chat_id,
        message_id,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    
    if video.get('thumbnail'):
        try:
            bot.send_photo(
                chat_id,
                video['thumbnail'],
                caption="🍽️ صورة من الفيديو"
            )
        except:
            pass

# ==================== مسارات Webhook ====================
@app.route('/', methods=['GET'])
def index():
    return "🍳 بوت الوصفات يعمل بنجاح! 🚀", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '❌ خطأ في الطلب', 403

@app.route('/health', methods=['GET'])
def health():
    return "✅ البوت سليم", 200

@app.route('/setup', methods=['GET'])
def setup_webhook():
    """تعيين webhook يدوياً"""
    webhook_url = f"{RENDER_URL}/webhook"
    set_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}"
    response = requests.get(set_url)
    
    if response.status_code == 200 and response.json().get('ok'):
        return f"✅ تم تعيين webhook بنجاح: {webhook_url}", 200
    else:
        return f"❌ فشل في تعيين webhook: {response.text}", 400

# ==================== تشغيل البوت ====================
if __name__ == '__main__':
    print("=" * 60)
    print("🍳 بوت الوصفات - نسخة Webhook لـ Render")
    print("=" * 60)
    
    # حذف أي webhook قديم
    delete_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook"
    delete_response = requests.post(delete_url, json={"drop_pending_updates": True})
    
    if delete_response.status_code == 200:
        print("✅ تم حذف webhook القديم")
    
    # تعيين webhook جديد
    webhook_url = f"{RENDER_URL}/webhook"
    set_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    
    webhook_config = {
        "url": webhook_url,
        "drop_pending_updates": True,
        "max_connections": 40
    }
    
    set_response = requests.post(set_url, json=webhook_config)
    
    if set_response.status_code == 200 and set_response.json().get('ok'):
        print(f"✅ تم تعيين webhook بنجاح: {webhook_url}")
        
        # التحقق من webhook
        info_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getWebhookInfo"
        info_response = requests.get(info_url)
        if info_response.status_code == 200:
            info = info_response.json()
            if info.get('ok'):
                print(f"📊 معلومات webhook:")
                print(f"   - الرابط: {info['result'].get('url')}")
                print(f"   - في الانتظار: {info['result'].get('pending_update_count', 0)} تحديث")
    else:
        print(f"❌ فشل في تعيين webhook: {set_response.text}")
    
    print("\n🚀 البوت جاهز للعمل على Render...")
    print(f"🌐 رابط التطبيق: {RENDER_URL}")
    print(f"⚙️ رابط webhook: {webhook_url}")
    print("=" * 60)
    
    # تشغيل Flask
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
