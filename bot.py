"""
🍽️ بوت وصفات الطعام العالمي - Telegram Recipe Bot
يبحث في يوتيب عن وصفات ويحفظها في Excel
جاهز للرفع على Render
"""

import os
import json
import logging
import re
import time
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import requests

# ──────────────────────────────────────────────────────────────────────────
#  الإعدادات
# ──────────────────────────────────────────────────────────────────────────

BOT_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ")
EXCEL_FILE = "وصفات_الطعام.xlsx"
PORT       = int(os.environ.get("PORT", 8080))   # Render يحتاج HTTP server

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
#  ثوابت Excel
# ──────────────────────────────────────────────────────────────────────────

COLORS = {
    "header_bg": "1A1A2E",
    "header_fg": "FFFFFF",
    "row_odd":   "F8F4FF",
    "row_even":  "FFFFFF",
    "title_bg":  "16213E",
    "link":      "1565C0",
    "border":    "D0C4F7",
}

HEADERS = [
    "رقم", "اسم الوصفة", "النوع / الصنف", "الدولة / المطبخ",
    "وصف الوصفة", "رابط يوتيب", "القناة",
    "المدة (دقيقة)", "عدد المشاهدات", "تاريخ الإضافة", "ملاحظات",
]

MEAL_TYPES = [
    "وجبة فطور", "وجبة غداء", "وجبة عشاء",
    "حلويات وتحلية", "مشروبات وعصائر", "شوربة وحساء",
    "سلطات", "مقبلات وسناكس", "خبز وفطائر",
    "أطباق بحرية", "لحوم ودجاج", "أكل نباتي",
]

WORLD_CUISINES = [
    "عربي", "مصري", "سعودي", "مغربي", "لبناني", "سوري",
    "تركي", "إيطالي", "فرنسي", "هندي", "صيني", "ياباني",
    "كوري", "تايلاندي", "مكسيكي", "أمريكي", "يوناني",
    "إسباني", "بريطاني", "إثيوبي", "إيراني", "باكستاني",
    "روسي", "برازيلي", "أرجنتيني", "عالمي",
]

# حالات المستخدمين
user_states  = {}   # {chat_id: {"state": str, "data": dict}}
search_cache = {}   # {chat_id: {"videos": [...], "recipe_data": {...}}}

# ──────────────────────────────────────────────────────────────────────────
#  Excel
# ──────────────────────────────────────────────────────────────────────────

def _make_border():
    s = Side(style="thin", color=COLORS["border"])
    return Border(left=s, right=s, top=s, bottom=s)


def _init_sheet(ws):
    ws.sheet_view.rightToLeft = True
    ws.merge_cells("A1:K1")
    c = ws["A1"]
    c.value = "🍽️  قاعدة بيانات وصفات الطعام العالمية"
    c.font = Font(bold=True, size=16, color="FFFFFF", name="Arial")
    c.fill = PatternFill("solid", start_color=COLORS["title_bg"])
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 42

    border = _make_border()
    for i, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=2, column=i)
        cell.value = h
        cell.font = Font(bold=True, size=11, color="FFFFFF", name="Arial")
        cell.fill = PatternFill("solid", start_color=COLORS["header_bg"])
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    ws.row_dimensions[2].height = 30

    for i, w in enumerate([6, 28, 18, 18, 45, 40, 22, 12, 16, 18, 20], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A3"


def get_or_create_wb():
    if os.path.exists(EXCEL_FILE):
        return openpyxl.load_workbook(EXCEL_FILE)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "الوصفات"
    _init_sheet(ws)
    wb.save(EXCEL_FILE)
    return wb


def save_recipe(recipe: dict) -> int:
    wb = get_or_create_wb()
    ws = wb["الوصفات"]
    next_row = max(ws.max_row + 1, 3)
    num = next_row - 2
    border = _make_border()
    fill = COLORS["row_odd"] if num % 2 else COLORS["row_even"]

    row_data = [
        num,
        recipe.get("title", ""),
        recipe.get("meal_type", ""),
        recipe.get("cuisine", ""),
        recipe.get("description", ""),
        recipe.get("url", ""),
        recipe.get("channel", ""),
        recipe.get("duration", ""),
        recipe.get("views", ""),
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        recipe.get("notes", ""),
    ]

    for col, val in enumerate(row_data, 1):
        cell = ws.cell(row=next_row, column=col)
        cell.value = val
        cell.fill = PatternFill("solid", start_color=fill)
        cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
        cell.border = border
        if col == 6 and val:
            cell.hyperlink = val
            cell.font = Font(size=10, color=COLORS["link"], underline="single", name="Arial")
        else:
            cell.font = Font(size=10, name="Arial")

    ws.row_dimensions[next_row].height = 55
    wb.save(EXCEL_FILE)
    return num


def get_all_recipes() -> list:
    if not os.path.exists(EXCEL_FILE):
        return []
    wb = openpyxl.load_workbook(EXCEL_FILE, data_only=True)
    ws = wb["الوصفات"]
    recipes = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        if row[0] is not None:
            recipes.append({
                "num": row[0], "title": row[1] or "",
                "meal_type": row[2] or "", "cuisine": row[3] or "",
                "description": row[4] or "", "url": row[5] or "",
                "channel": row[6] or "", "duration": row[7] or "",
                "views": row[8] or "", "date": row[9] or "",
                "notes": row[10] or "",
            })
    return recipes

# ──────────────────────────────────────────────────────────────────────────
#  YouTube Search
# ──────────────────────────────────────────────────────────────────────────

def search_youtube(query: str, max_results: int = 6) -> list:
    """البحث في يوتيب باستخدام yt-dlp."""
    try:
        import yt_dlp

        ydl_opts = {
            "quiet":          True,
            "no_warnings":    True,
            "extract_flat":   True,
            "default_search": f"ytsearch{max_results}",
            "ignoreerrors":   True,
        }
        search_query = f"ytsearch{max_results}:{query} وصفة طبخ"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)

        if not info or "entries" not in info:
            return []

        videos = []
        for entry in info["entries"]:
            if not entry:
                continue
            duration_sec = entry.get("duration") or 0
            minutes = round(duration_sec / 60)
            view_count = entry.get("view_count") or 0
            if view_count >= 1_000_000:
                views = f"{view_count/1_000_000:.1f}M"
            elif view_count >= 1_000:
                views = f"{view_count/1_000:.0f}K"
            else:
                views = str(view_count) if view_count else "N/A"

            vid_id  = entry.get("id", "")
            url     = entry.get("url") or entry.get("webpage_url") or (
                      f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "")

            videos.append({
                "title":       entry.get("title", ""),
                "url":         url,
                "channel":     entry.get("uploader") or entry.get("channel", ""),
                "duration":    minutes,
                "views":       views,
                "description": (entry.get("description") or "")[:200],
            })
        return videos

    except Exception as e:
        logger.error(f"YouTube search error: {e}")
        # fallback: scraping بسيط
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp    = requests.get("https://www.youtube.com/results",
                                   params={"search_query": query + " وصفة طبخ", "hl": "ar"},
                                   headers=headers, timeout=12)
            ids    = list(dict.fromkeys(re.findall(r'"videoId":"([^"]{11})"', resp.text)))
            titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', resp.text)
            chans  = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', resp.text)
            videos = []
            for i, vid_id in enumerate(ids[:max_results]):
                videos.append({
                    "title":       titles[i] if i < len(titles) else f"وصفة {i+1}",
                    "url":         f"https://www.youtube.com/watch?v={vid_id}",
                    "channel":     chans[i] if i < len(chans) else "قناة يوتيب",
                    "duration":    0, "views": "N/A", "description": "",
                })
            return videos
        except Exception as e2:
            logger.error(f"Fallback search error: {e2}")
            return []

# ──────────────────────────────────────────────────────────────────────────
#  Telegram API helpers
# ──────────────────────────────────────────────────────────────────────────

API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg_post(method: str, **kwargs):
    try:
        r = requests.post(f"{API}/{method}", json=kwargs, timeout=15)
        return r.json()
    except Exception as e:
        logger.error(f"tg_post {method}: {e}")
        return {}


def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    tg_post("sendMessage", **payload)


def send_document(chat_id, file_path, caption=""):
    try:
        with open(file_path, "rb") as f:
            requests.post(
                f"{API}/sendDocument",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"document": f},
                timeout=30,
            )
    except Exception as e:
        logger.error(f"send_document: {e}")


def kb(buttons):
    return {"keyboard": buttons, "resize_keyboard": True, "one_time_keyboard": True}


def main_kb():
    return kb([
        ["🔍 بحث عن وصفة", "📋 عرض جميع الوصفات"],
        ["📥 تحميل Excel",  "📊 إحصائيات"],
        ["❓ مساعدة"],
    ])

# ──────────────────────────────────────────────────────────────────────────
#  أوامر البوت
# ──────────────────────────────────────────────────────────────────────────

def cmd_start(chat_id):
    user_states[chat_id] = {"state": "idle", "data": {}}
    send_message(chat_id,
        "👨‍🍳 <b>أهلاً بك في بوت وصفات الطعام العالمي!</b>\n\n"
        "🍽️ يمكنني مساعدتك في:\n"
        "• البحث عن أي وصفة طعام في يوتيب 🎥\n"
        "• حفظ الوصفات في ملف Excel 📊\n"
        "• البحث حسب النوع، الدولة، أو الاسم 🔍\n"
        "• عرض جميع وصفاتك المحفوظة 📋\n\n"
        "📌 <b>اكتب اسم الوجبة للبدء أو اضغط على زر:</b>",
        reply_markup=main_kb())


def cmd_help(chat_id):
    send_message(chat_id,
        "📖 <b>دليل الاستخدام:</b>\n\n"
        "1️⃣ اكتب اسم الوجبة: <code>كبسة</code>، <code>بيتزا</code>، <code>سوشي</code>...\n"
        "2️⃣ اختر نوع الوجبة\n"
        "3️⃣ اختر المطبخ / الدولة\n"
        "4️⃣ اختر الفيديو من نتائج يوتيب\n"
        "5️⃣ يُحفظ تلقائياً في Excel ✅\n\n"
        "📥 اضغط <b>تحميل Excel</b> للحصول على ملف الوصفات",
        reply_markup=main_kb())


def cmd_all(chat_id):
    recipes = get_all_recipes()
    if not recipes:
        send_message(chat_id, "📭 لا توجد وصفات محفوظة بعد!\nابدأ بالبحث عن وصفة.", reply_markup=main_kb())
        return

    text = f"📋 <b>وصفاتي المحفوظة ({len(recipes)} وصفة):</b>\n\n"
    for r in recipes[-20:]:
        text += (
            f"<b>{r['num']}. {r['title']}</b>\n"
            f"   🍴 {r['meal_type']} | 🌍 {r['cuisine']}\n"
            f"   📺 {r['channel']} | ⏱ {r['duration']} د\n"
            f"   🔗 <a href='{r['url']}'>مشاهدة الفيديو</a>\n"
            f"   📅 {r['date']}\n\n"
        )
    if len(recipes) > 20:
        text += f"<i>تم عرض آخر 20 من أصل {len(recipes)}</i>"
    send_message(chat_id, text, reply_markup=main_kb())


def cmd_excel(chat_id):
    get_or_create_wb()
    send_message(chat_id, "📤 جاري إرسال ملف Excel...")
    send_document(chat_id, EXCEL_FILE,
                  caption=f"📊 <b>ملف وصفات الطعام</b>\n📝 عدد الوصفات: {len(get_all_recipes())}")


def cmd_stats(chat_id):
    recipes = get_all_recipes()
    if not recipes:
        send_message(chat_id, "لا توجد إحصائيات بعد!", reply_markup=main_kb())
        return
    types, cuisines = {}, {}
    for r in recipes:
        t = r["meal_type"] or "غير محدد"
        c = r["cuisine"] or "غير محدد"
        types[t] = types.get(t, 0) + 1
        cuisines[c] = cuisines.get(c, 0) + 1

    top_t = sorted(types.items(), key=lambda x: x[1], reverse=True)[:5]
    top_c = sorted(cuisines.items(), key=lambda x: x[1], reverse=True)[:5]

    text = f"📊 <b>إحصائيات:</b>\n\n📝 الإجمالي: <b>{len(recipes)}</b> وصفة\n\n🍴 <b>أكثر الأنواع:</b>\n"
    for t, n in top_t:
        text += f"  • {t}: {n}\n"
    text += "\n🌍 <b>أكثر المطابخ:</b>\n"
    for c, n in top_c:
        text += f"  • {c}: {n}\n"
    send_message(chat_id, text, reply_markup=main_kb())

# ──────────────────────────────────────────────────────────────────────────
#  تدفق البحث
# ──────────────────────────────────────────────────────────────────────────

def start_search(chat_id):
    user_states[chat_id] = {"state": "waiting_name", "data": {}}
    send_message(chat_id,
                 "🔍 <b>اكتب اسم الوجبة التي تريد البحث عنها:</b>\n"
                 "مثال: كبسة، برياني، بيتزا، كريم كراميل...",
                 reply_markup={"remove_keyboard": True})


def ask_meal_type(chat_id, name):
    rows = [MEAL_TYPES[i:i+3] for i in range(0, len(MEAL_TYPES), 3)]
    rows.append(["⏭️ تخطي"])
    send_message(chat_id, f"🍴 <b>نوع وجبة '{name}'؟</b>", reply_markup=kb(rows))


def ask_cuisine(chat_id):
    rows = [WORLD_CUISINES[i:i+4] for i in range(0, len(WORLD_CUISINES), 4)]
    rows.append(["⏭️ تخطي"])
    send_message(chat_id, "🌍 <b>من أي دولة / مطبخ؟</b>", reply_markup=kb(rows))


def do_search(chat_id, state_info):
    d = state_info["data"]
    parts = [d.get("name", "")]
    if d.get("cuisine"):  parts.append(d["cuisine"])
    if d.get("meal_type"): parts.append(d["meal_type"])
    query = " ".join(parts)

    send_message(chat_id,
                 f"🔍 <b>جاري البحث:</b> {query}\n⏳ انتظر لحظة...",
                 reply_markup={"remove_keyboard": True})

    videos = search_youtube(query)
    if not videos:
        send_message(chat_id, "❌ لم أجد نتائج. جرّب كلمات أخرى.", reply_markup=main_kb())
        user_states[chat_id] = {"state": "idle", "data": {}}
        return

    search_cache[chat_id] = {
        "videos": videos,
        "recipe_data": {"meal_type": d.get("meal_type", ""), "cuisine": d.get("cuisine", "")},
    }

    text = f"🎥 <b>نتائج البحث عن: {query}</b>\n\n"
    for i, v in enumerate(videos, 1):
        dur   = f"{v['duration']} د" if v["duration"] else "N/A"
        views = v["views"] or "N/A"
        text += (
            f"<b>{i}. {v['title']}</b>\n"
            f"   📺 {v['channel']}  |  ⏱ {dur}  |  👁 {views}\n"
            f"   🔗 <a href='{v['url']}'>مشاهدة</a>\n\n"
        )
    text += "📌 <b>اكتب رقم الفيديو لحفظه أو 0 للإلغاء:</b>"

    nums = [[str(i) for i in range(1, len(videos)+1)], ["0️⃣ إلغاء"]]
    user_states[chat_id] = {"state": "waiting_choice", "data": d}
    send_message(chat_id, text, reply_markup=kb(nums))

# ──────────────────────────────────────────────────────────────────────────
#  معالج الرسائل
# ──────────────────────────────────────────────────────────────────────────

def handle_update(update: dict):
    if "message" not in update:
        return
    msg     = update["message"]
    chat_id = msg["chat"]["id"]
    text    = msg.get("text", "").strip()
    if not text:
        return

    si    = user_states.get(chat_id, {"state": "idle", "data": {}})
    state = si["state"]

    # ── أوامر دائمة ──
    if text in ("/start",):
        cmd_start(chat_id); return
    if text in ("/help", "❓ مساعدة"):
        cmd_help(chat_id); return
    if text in ("/all", "📋 عرض جميع الوصفات"):
        cmd_all(chat_id); return
    if text in ("/excel", "📥 تحميل Excel"):
        cmd_excel(chat_id); return
    if text in ("/search", "🔍 بحث عن وصفة"):
        start_search(chat_id); return
    if text in ("/stats", "📊 إحصائيات"):
        cmd_stats(chat_id); return

    # ── حالات المحادثة ──
    if state == "waiting_name":
        si["data"]["name"] = text
        user_states[chat_id] = {"state": "waiting_meal_type", "data": si["data"]}
        ask_meal_type(chat_id, text)

    elif state == "waiting_meal_type":
        si["data"]["meal_type"] = "" if "تخطي" in text else text
        user_states[chat_id] = {"state": "waiting_cuisine", "data": si["data"]}
        ask_cuisine(chat_id)

    elif state == "waiting_cuisine":
        si["data"]["cuisine"] = "" if "تخطي" in text else text
        do_search(chat_id, si)

    elif state == "waiting_choice":
        cache  = search_cache.get(chat_id, {})
        videos = cache.get("videos", [])
        try:
            choice = int(re.search(r"\d+", text).group())
        except Exception:
            send_message(chat_id, "❌ أدخل رقماً صحيحاً!"); return

        if choice == 0:
            user_states[chat_id] = {"state": "idle", "data": {}}
            send_message(chat_id, "✅ تم الإلغاء.", reply_markup=main_kb()); return

        if not (1 <= choice <= len(videos)):
            send_message(chat_id, f"❌ اختر رقم من 1 إلى {len(videos)}"); return

        selected = videos[choice - 1]
        si["data"]["selected"] = selected
        si["data"].update(cache.get("recipe_data", {}))
        user_states[chat_id] = {"state": "waiting_notes", "data": si["data"]}
        send_message(chat_id,
                     f"✅ اخترت: <b>{selected['title']}</b>\n\n"
                     "📝 أضف ملاحظاتك أو اكتب <b>تخطي</b>:",
                     reply_markup=kb([["⏭️ تخطي"]]))

    elif state == "waiting_notes":
        notes   = "" if "تخطي" in text else text
        video   = si["data"].get("selected", {})
        recipe  = {
            "title":       video.get("title", ""),
            "meal_type":   si["data"].get("meal_type", ""),
            "cuisine":     si["data"].get("cuisine", ""),
            "url":         video.get("url", ""),
            "channel":     video.get("channel", ""),
            "duration":    video.get("duration", 0),
            "views":       video.get("views", ""),
            "description": video.get("description", ""),
            "notes":       notes,
        }
        num = save_recipe(recipe)
        user_states[chat_id] = {"state": "idle", "data": {}}
        search_cache.pop(chat_id, None)
        send_message(chat_id,
            f"🎉 <b>تم حفظ الوصفة بنجاح!</b>\n\n"
            f"📌 رقم: <b>#{num}</b>\n"
            f"🍽️ <b>{recipe['title']}</b>\n"
            f"🍴 {recipe['meal_type'] or 'N/A'}  |  🌍 {recipe['cuisine'] or 'N/A'}\n"
            f"📺 {recipe['channel']}  |  ⏱ {recipe['duration']} د\n\n"
            "💾 تم الحفظ في Excel!\n"
            "📥 اضغط <b>تحميل Excel</b> للحصول على الملف",
            reply_markup=main_kb())

    else:
        # إدخال مباشر لاسم وجبة
        if len(text) > 2:
            si = {"state": "waiting_meal_type", "data": {"name": text}}
            user_states[chat_id] = si
            ask_meal_type(chat_id, text)
        else:
            cmd_start(chat_id)

# ──────────────────────────────────────────────────────────────────────────
#  Long Polling
# ──────────────────────────────────────────────────────────────────────────

def run_polling():
    logger.info("🤖 بدء تشغيل البوت (long polling)...")
    get_or_create_wb()
    offset = 0
    while True:
        try:
            resp = requests.get(
                f"{API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"API: {data}")
                time.sleep(3)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    handle_update(upd)
                except Exception as e:
                    logger.error(f"handle_update: {e}", exc_info=True)
        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            logger.error(f"polling: {e}")
            time.sleep(5)

# ──────────────────────────────────────────────────────────────────────────
#  HTTP Server (مطلوب لـ Render حتى لا يتوقف الـ service)
# ──────────────────────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"OK - Recipe Bot is running"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass   # تعطيل logs HTTP المزعجة


def run_http():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"🌐 HTTP server on port {PORT}")
    server.serve_forever()

# ──────────────────────────────────────────────────────────────────────────
#  نقطة البدء
# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # تشغيل HTTP في خيط منفصل
    t = threading.Thread(target=run_http, daemon=True)
    t.start()
    # تشغيل البوت في الخيط الرئيسي
    run_polling()
