"""
بوت وصفات الطعام - اكتب اسم الوجبة مباشرة
"""
import os, re, time, logging, threading, json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import requests

# ══════════════════════════════════════════════════════
BOT_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "8719774473:AAG6_COb6UElTsmzxlJJNaltmrJoL5QsqvQ")
EXCEL_FILE = "wosafat.xlsx"
PORT       = int(os.environ.get("PORT", 8080))

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

CONTINENT_MAP = {
    "مصري":"أفريقيا","مغربي":"أفريقيا","إثيوبي":"أفريقيا",
    "سعودي":"آسيا","عربي":"آسيا","لبناني":"آسيا","سوري":"آسيا",
    "تركي":"آسيا","هندي":"آسيا","صيني":"آسيا","ياباني":"آسيا",
    "كوري":"آسيا","تايلاندي":"آسيا","إيراني":"آسيا","باكستاني":"آسيا",
    "إيطالي":"أوروبا","فرنسي":"أوروبا","يوناني":"أوروبا",
    "إسباني":"أوروبا","بريطاني":"أوروبا","روسي":"أوروبا",
    "مكسيكي":"أمريكا اللاتينية","برازيلي":"أمريكا اللاتينية","أرجنتيني":"أمريكا اللاتينية",
    "أمريكي":"أمريكا الشمالية","عالمي":"العالم",
}

# حالات المستخدمين
user_states  = {}   # {cid: {"state":..., "data":...}}
search_cache = {}   # {cid: [videos]}
recipe_cache = {}   # {cid: recipe_dict}

# ══════════════════════════════════════════════════════
#  Excel
# ══════════════════════════════════════════════════════
COLORS = {"title":"1A1A2E","header":"16213E","odd":"F3F0FF","even":"FFFFFF","link":"1565C0","border":"C9C0E8"}
HEADERS = ["رقم","اسم الوصفة","الدولة / المطبخ","القارة","المكونات","طريقة التحضير","رابط يوتيب","القناة","المدة (د)","المشاهدات","تاريخ الإضافة","ملاحظات"]

def _b():
    s = Side(style="thin", color=COLORS["border"])
    return Border(left=s, right=s, top=s, bottom=s)

def _init_sheet(ws):
    ws.sheet_view.rightToLeft = True
    ws.merge_cells("A1:L1")
    c = ws["A1"]
    c.value = "قاعدة بيانات وصفات الطعام العالمية"
    c.font = Font(bold=True, size=16, color="FFFFFF", name="Arial")
    c.fill = PatternFill("solid", start_color=COLORS["title"])
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 42
    b = _b()
    for i, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=2, column=i)
        cell.value = h
        cell.font = Font(bold=True, size=10, color="FFFFFF", name="Arial")
        cell.fill = PatternFill("solid", start_color=COLORS["header"])
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = b
    ws.row_dimensions[2].height = 28
    for i, w in enumerate([5, 26, 16, 14, 42, 55, 38, 20, 8, 12, 16, 18], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A3"

def get_wb():
    if os.path.exists(EXCEL_FILE):
        return openpyxl.load_workbook(EXCEL_FILE)
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "الوصفات"
    _init_sheet(ws); wb.save(EXCEL_FILE)
    return wb

def save_recipe(r: dict) -> int:
    wb = get_wb(); ws = wb["الوصفات"]
    next_row = max(ws.max_row + 1, 3)
    num = next_row - 2
    b = _b()
    fill = COLORS["odd"] if num % 2 else COLORS["even"]
    row_data = [
        num, r.get("title",""), r.get("cuisine",""), r.get("continent",""),
        r.get("ingredients",""), r.get("steps",""), r.get("url",""),
        r.get("channel",""), r.get("duration",""), r.get("views",""),
        datetime.now().strftime("%Y-%m-%d %H:%M"), r.get("notes",""),
    ]
    for col, val in enumerate(row_data, 1):
        cell = ws.cell(row=next_row, column=col)
        cell.value = val
        cell.fill = PatternFill("solid", start_color=fill)
        cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
        cell.border = b
        if col == 7 and val:
            cell.hyperlink = val
            cell.font = Font(size=10, color=COLORS["link"], underline="single", name="Arial")
        else:
            cell.font = Font(size=10, name="Arial")
    ws.row_dimensions[next_row].height = 90
    wb.save(EXCEL_FILE)
    return num

def get_all_recipes():
    if not os.path.exists(EXCEL_FILE): return []
    wb = openpyxl.load_workbook(EXCEL_FILE, data_only=True)
    ws = wb["الوصفات"]; out = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        if row[0] is not None:
            out.append({"num":row[0],"title":row[1] or "","cuisine":row[2] or "",
                        "url":row[6] or "","channel":row[7] or "","date":row[10] or ""})
    return out

# ══════════════════════════════════════════════════════
#  استخراج المكونات وطريقة التحضير من الوصف
# ══════════════════════════════════════════════════════
ING_KEYWORDS  = ['المكونات','مكونات','مقادير','المقادير','ingredients','what you need','you will need','ستحتاج','تحتاج']
STEP_KEYWORDS = ['طريقة','التحضير','الخطوات','طريقه','الإعداد','preparation','instructions','how to','steps','method']
STOP_AFTER_ING = ['طريقة','التحضير','الخطوات','preparation','instructions','how to','steps']

def extract_ingredients(desc: str) -> list:
    lines = desc.replace('\r','').split('\n')
    result = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_section and result: break
            continue
        lower = stripped.lower()
        # دخول قسم المكونات
        if not in_section and any(k in stripped for k in ING_KEYWORDS):
            in_section = True; continue
        # خروج إذا بدأ قسم التحضير
        if in_section and any(k in stripped for k in STOP_AFTER_ING):
            break
        if in_section:
            clean = re.sub(r'^[\-•*✓✔▪◦▸►\d]+[\.\)\-\s]*', '', stripped).strip()
            # فلتر: يجب أن يكون المكون منطقياً (يحتوي رقم أو وحدة قياس أو اسم مكون)
            if clean and len(clean) > 2 and len(clean) < 120:
                result.append(clean)
    return result

def extract_steps(desc: str) -> list:
    lines = desc.replace('\r','').split('\n')
    result = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if not stripped: continue
        lower = stripped.lower()
        if not in_section and any(k in stripped for k in STEP_KEYWORDS):
            in_section = True; continue
        if in_section:
            # خطوة مرقمة أو سطر تعليمي
            clean = re.sub(r'^[\d]+[\.\:\-\)]\s*', '', stripped).strip()
            # فلتر: خطوة منطقية (فعل + نص)
            if clean and len(clean) > 8 and len(clean) < 400:
                # تجاهل سطور مثل "شكراً للمشاهدة" أو "subscribe"
                skip_words = ['subscribe','اشترك','لايك','like','شكرا','متابعة','instagram','facebook','تيك توك']
                if not any(sw in clean.lower() for sw in skip_words):
                    result.append(clean)
    return result

def parse_cuisine_from_title(title: str) -> tuple:
    """يستخرج الدولة والقارة من عنوان الفيديو."""
    title_lower = title.lower()
    for cuisine, continent in CONTINENT_MAP.items():
        if cuisine in title_lower or cuisine in title:
            return cuisine, continent
    return "", ""

# ══════════════════════════════════════════════════════
#  جلب وصف الفيديو الكامل عبر yt-dlp
# ══════════════════════════════════════════════════════
def fetch_video_details(url: str) -> dict:
    """يجلب الوصف الكامل للفيديو لاستخراج المكونات والخطوات."""
    try:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,   # مهم: وضع كامل للحصول على الوصف
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        desc = info.get("description") or ""
        return {
            "description": desc,
            "title":       info.get("title",""),
            "channel":     info.get("uploader") or info.get("channel",""),
            "duration":    round((info.get("duration") or 0) / 60),
            "views":       _fmt_views(info.get("view_count") or 0),
        }
    except Exception as e:
        logger.error(f"fetch_video_details: {e}")
        return {"description":"","title":"","channel":"","duration":0,"views":"N/A"}

def _fmt_views(vc: int) -> str:
    if vc >= 1_000_000: return f"{vc/1e6:.1f}M"
    if vc >= 1_000:     return f"{vc/1e3:.0f}K"
    return str(vc) if vc else "N/A"

# ══════════════════════════════════════════════════════
#  بحث يوتيب
# ══════════════════════════════════════════════════════
def search_youtube(query: str, max_results: int = 6) -> list:
    try:
        import yt_dlp
        opts = {"quiet":True,"no_warnings":True,"extract_flat":True,"ignoreerrors":True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query} وصفة", download=False)
        if not info or "entries" not in info: raise ValueError("no entries")
        videos = []
        for e in (info.get("entries") or []):
            if not e: continue
            secs = e.get("duration") or 0
            vid  = e.get("id","")
            url  = e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
            videos.append({
                "title":    e.get("title",""),
                "url":      url,
                "channel":  e.get("uploader") or e.get("channel",""),
                "duration": round(secs/60),
                "views":    _fmt_views(e.get("view_count") or 0),
            })
        return videos
    except Exception as ex:
        logger.error(f"yt-dlp search: {ex}")
        # fallback scraping
        try:
            hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp = requests.get("https://www.youtube.com/results",
                                params={"search_query": query+" وصفة طبخ","hl":"ar"},
                                headers=hdrs, timeout=12)
            ids    = list(dict.fromkeys(re.findall(r'"videoId":"([^"]{11})"', resp.text)))
            titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', resp.text)
            chans  = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', resp.text)
            return [{"title":titles[i] if i<len(titles) else f"وصفة {i+1}",
                     "url":f"https://www.youtube.com/watch?v={v}",
                     "channel":chans[i] if i<len(chans) else "يوتيب",
                     "duration":0,"views":"N/A"}
                    for i,v in enumerate(ids[:max_results])]
        except Exception as ex2:
            logger.error(f"fallback: {ex2}"); return []

# ══════════════════════════════════════════════════════
#  Telegram helpers
# ══════════════════════════════════════════════════════
def tg(method, **kw):
    try: return requests.post(f"{API}/{method}", json=kw, timeout=15).json()
    except Exception as e: logger.error(f"tg/{method}: {e}"); return {}

def send(cid, text, markup=None):
    p = {"chat_id":cid,"text":text,"parse_mode":"HTML","disable_web_page_preview":True}
    if markup: p["reply_markup"] = markup
    tg("sendMessage", **p)

def send_doc(cid, path, caption=""):
    try:
        with open(path,"rb") as f:
            requests.post(f"{API}/sendDocument",
                data={"chat_id":cid,"caption":caption,"parse_mode":"HTML"},
                files={"document":f}, timeout=30)
    except Exception as e: logger.error(f"send_doc: {e}")

def kb(rows):       return {"keyboard":rows,"resize_keyboard":True,"one_time_keyboard":True}
def rm_kb():        return {"remove_keyboard":True}
def main_kb():      return kb([["📋 وصفاتي","📥 تحميل Excel"],["📊 إحصائيات","❓ مساعدة"]])
def yes_no_kb():    return kb([["✅ نعم، احفظها","❌ لا شكراً"]])
def num_kb(n):      return kb([[str(i) for i in range(1, n+1)], ["0️⃣ إلغاء"]])

# ══════════════════════════════════════════════════════
#  تنسيق رسالة الوصفة
# ══════════════════════════════════════════════════════
def format_recipe_msg(video: dict, details: dict, cuisine: str, continent: str) -> str:
    title      = video.get("title","")
    channel    = video.get("channel","") or details.get("channel","")
    url        = video.get("url","")
    duration   = video.get("duration") or details.get("duration",0)
    views      = video.get("views","N/A") or details.get("views","N/A")
    ingredients = details.get("ingredients",[])
    steps       = details.get("steps",[])

    msg  = f"🍽️ <b>{title}</b>\n"
    if cuisine:   msg += f"🌍 الدولة: <b>{cuisine}</b>\n"
    if continent: msg += f"🗺️ القارة: <b>{continent}</b>\n"

    info = []
    if channel:  info.append(f"📺 {channel}")
    if duration: info.append(f"⏱ {duration} دقيقة")
    if views and views != "N/A": info.append(f"👁 {views}")
    if info: msg += "  |  ".join(info) + "\n"

    # المكونات
    if ingredients:
        msg += "\n<b>🛒 المكونات:</b>\n"
        for ing in ingredients:
            msg += f"• {ing}\n"
    else:
        msg += "\n⚠️ <i>لم يُذكر قائمة المكونات في وصف الفيديو</i>\n"

    # طريقة التحضير
    if steps:
        msg += "\n<b>👨‍🍳 طريقة التحضير:</b>\n"
        for i, step in enumerate(steps, 1):
            msg += f"\n<b>{i}.</b> {step}\n"
    else:
        msg += "\n⚠️ <i>لم تُذكر طريقة التحضير في وصف الفيديو</i>\n"

    msg += f"\n🔗 <a href='{url}'>▶️ مشاهدة الفيديو</a>\n"
    msg += "\n💾 <b>هل تريد حفظ هذه الوصفة في Excel؟</b>"
    return msg

# ══════════════════════════════════════════════════════
#  منطق البحث والعرض
# ══════════════════════════════════════════════════════
def do_search(cid: int, query: str):
    """بحث فوري بمجرد كتابة اسم الوجبة."""
    send(cid, f"🔍 جاري البحث عن: <b>{query}</b> ...", markup=rm_kb())
    videos = search_youtube(query)

    if not videos:
        send(cid, "❌ لم أجد نتائج، جرّب كلمة أخرى.", markup=main_kb())
        return

    search_cache[cid] = videos

    text = f"🎥 <b>وصفات '{query}' على يوتيب:</b>\n\n"
    for i, v in enumerate(videos, 1):
        dur  = f"⏱ {v['duration']} د" if v["duration"] else ""
        meta = f"  {dur}" if dur else ""
        text += (
            f"<b>{i}. {v['title']}</b>\n"
            f"   📺 {v['channel']}{meta}\n\n"
        )
    text += "📌 <b>اكتب رقم الوصفة لرؤية التفاصيل كاملة:</b>"

    user_states[cid] = {"state": "waiting_choice", "data": {"query": query}}
    send(cid, text, markup=num_kb(len(videos)))


def show_recipe(cid: int, video: dict):
    """جلب وصف الفيديو واستخراج الوصفة الكاملة."""
    send(cid, "⏳ جاري جلب الوصفة الكاملة...", markup=rm_kb())

    # جلب الوصف الكامل من يوتيب
    details_raw = fetch_video_details(video["url"])
    desc        = details_raw.get("description", "")

    # استخراج المكونات والخطوات
    ingredients = extract_ingredients(desc)
    steps       = extract_steps(desc)

    # استخراج الدولة من العنوان أو الوصف
    cuisine, continent = parse_cuisine_from_title(video["title"])
    if not cuisine:
        cuisine, continent = parse_cuisine_from_title(desc[:200])

    details = {
        "ingredients": ingredients,
        "steps":       steps,
        "channel":     details_raw.get("channel",""),
        "duration":    details_raw.get("duration", video.get("duration",0)),
        "views":       details_raw.get("views", video.get("views","N/A")),
    }

    # حفظ في الكاش
    recipe_cache[cid] = {
        "title":       video["title"],
        "cuisine":     cuisine,
        "continent":   continent,
        "ingredients": "\n".join(f"• {x}" for x in ingredients),
        "steps":       "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)),
        "url":         video["url"],
        "channel":     details["channel"] or video.get("channel",""),
        "duration":    details["duration"],
        "views":       details["views"],
        "notes":       "",
    }

    msg = format_recipe_msg(video, details, cuisine, continent)
    user_states[cid] = {"state": "waiting_save", "data": {}}
    send(cid, msg, markup=yes_no_kb())

# ══════════════════════════════════════════════════════
#  معالج التحديثات
# ══════════════════════════════════════════════════════
def handle_update(update: dict):
    if "message" not in update: return
    msg  = update["message"]
    cid  = msg["chat"]["id"]
    text = msg.get("text","").strip()
    if not text: return

    si    = user_states.get(cid, {"state":"idle","data":{}})
    state = si["state"]

    # ── أوامر ثابتة ──────────────────────────────────
    if text == "/start":
        user_states[cid] = {"state":"idle","data":{}}
        send(cid,
            "👨‍🍳 <b>بوت وصفات الطعام العالمي</b>\n\n"
            "اكتب اسم أي وجبة مباشرة وسأجلب لك:\n"
            "🛒 المكونات\n"
            "👨‍🍳 طريقة التحضير خطوة بخطوة\n"
            "📊 حفظ في Excel\n\n"
            "<b>مثال:</b>  كبسة  |  بيتزا  |  سوشي  |  برياني",
            markup=main_kb())
        return

    if text in ("❓ مساعدة", "/help"):
        send(cid,
            "📖 <b>طريقة الاستخدام:</b>\n\n"
            "• اكتب اسم الوجبة مباشرة\n"
            "• اختر رقم الفيديو المناسب\n"
            "• استقبل الوصفة الكاملة\n"
            "• احفظها في Excel\n\n"
            "📥 <b>تحميل Excel</b> → كل وصفاتك المحفوظة",
            markup=main_kb())
        return

    if text in ("📋 وصفاتي", "/all"):
        recs = get_all_recipes()
        if not recs:
            send(cid, "📭 لا توجد وصفات محفوظة بعد!", markup=main_kb()); return
        t = f"📋 <b>وصفاتي ({len(recs)}):</b>\n\n"
        for r in recs[-20:]:
            t += f"<b>{r['num']}. {r['title']}</b>  |  🌍 {r['cuisine']}\n🔗 <a href='{r['url']}'>مشاهدة</a>  |  📅 {r['date']}\n\n"
        if len(recs) > 20: t += f"<i>آخر 20 من {len(recs)}</i>"
        send(cid, t, markup=main_kb()); return

    if text in ("📥 تحميل Excel", "/excel"):
        get_wb()
        send(cid, "📤 جاري الإرسال...")
        send_doc(cid, EXCEL_FILE, caption=f"📊 <b>وصفاتك</b> — {len(get_all_recipes())} وصفة")
        return

    if text in ("📊 إحصائيات", "/stats"):
        recs = get_all_recipes()
        if not recs:
            send(cid, "لا توجد إحصائيات بعد!", markup=main_kb()); return
        cuisines = {}
        for r in recs:
            c = r["cuisine"] or "غير محدد"
            cuisines[c] = cuisines.get(c,0) + 1
        t = f"📊 <b>إحصائياتك:</b>\n\n📝 الإجمالي: <b>{len(recs)}</b> وصفة\n\n🌍 <b>المطابخ:</b>\n"
        for c, n in sorted(cuisines.items(), key=lambda x: -x[1])[:8]:
            t += f"  • {c}: {n}\n"
        send(cid, t, markup=main_kb()); return

    # ── حالة: انتظار حفظ ─────────────────────────────
    if state == "waiting_save":
        if "نعم" in text:
            r   = recipe_cache.pop(cid, {})
            num = save_recipe(r)
            send(cid,
                f"✅ <b>تم الحفظ!</b>\n"
                f"📌 رقم الوصفة: <b>#{num}</b>\n"
                f"🍽️ <b>{r.get('title','')}</b>",
                markup=main_kb())
        else:
            recipe_cache.pop(cid, None)
            send(cid, "تم الإلغاء. اكتب اسم وجبة أخرى.", markup=main_kb())
        user_states[cid] = {"state":"idle","data":{}}
        return

    # ── حالة: انتظار اختيار رقم الفيديو ─────────────
    if state == "waiting_choice":
        videos = search_cache.get(cid, [])
        try:    choice = int(re.search(r"\d+", text).group())
        except: send(cid, "❌ أدخل رقماً صحيحاً!"); return

        if choice == 0:
            user_states[cid] = {"state":"idle","data":{}}
            send(cid, "تم الإلغاء.", markup=main_kb()); return
        if not (1 <= choice <= len(videos)):
            send(cid, f"❌ اختر من 1 إلى {len(videos)}"); return

        search_cache.pop(cid, None)
        show_recipe(cid, videos[choice - 1])
        return

    # ── أي نص آخر = بحث مباشر ────────────────────────
    if len(text) > 1 and not text.startswith("/"):
        do_search(cid, text)
    else:
        send(cid, "اكتب اسم وجبة للبحث عنها.", markup=main_kb())

# ══════════════════════════════════════════════════════
#  HTTP Server + Long Polling
# ══════════════════════════════════════════════════════
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

def run_http():
    HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()

def delete_webhook():
    try:
        r = requests.get(f"{API}/deleteWebhook",
                         params={"drop_pending_updates": True}, timeout=10).json()
        logger.info("webhook deleted" if r.get("ok") else f"deleteWebhook: {r}")
    except Exception as e:
        logger.error(f"deleteWebhook: {e}")

def run_polling():
    logger.info("Starting bot...")
    delete_webhook()
    time.sleep(1)
    get_wb()
    offset = 0
    while True:
        try:
            resp = requests.get(f"{API}/getUpdates",
                                params={"offset": offset, "timeout": 30},
                                timeout=35).json()
            if not resp.get("ok"):
                logger.error(f"API: {resp}"); time.sleep(3); continue
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                try:    handle_update(upd)
                except Exception as e: logger.error(f"handle_update: {e}", exc_info=True)
        except requests.exceptions.Timeout: continue
        except Exception as e:
            logger.error(f"polling: {e}"); time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    run_polling()
