import requests, time, json, os, calendar
from config import TOKEN, CHAT_ID, TD_KEY

CHAT_ID = str(CHAT_ID)
DAILY_HOUR = 8        # ساعة التقرير اليومي (UTC)
EVERY = 300           # فحص كل 5 دقائق
VOL_MULT = 3.0        # تنبيه تذبذب: شمعة اكبر من 3 اضعاف ATR
MAX_ALERTS = 10
STATE = "state6.json"
API = f"https://api.telegram.org/bot{TOKEN}/"
cache = {"t": 0, "rows": None}

def api(method, **p):
    return requests.post(API + method, data=p, timeout=40).json()

def send(msg):
    print(msg)
    try:
        api("sendMessage", chat_id=CHAT_ID, text=msg)
    except Exception as e:
        print("telegram error:", e)

def get_rows(maxage=240):
    if cache["rows"] and time.time() - cache["t"] < maxage:
        return cache["rows"]
    url = ("https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=15min"
           f"&outputsize=300&order=ASC&timezone=UTC&apikey={TD_KEY}")
    d = requests.get(url, timeout=20).json()
    if d.get("status") != "ok":
        raise Exception(d.get("message", "twelvedata error"))
    rows = []
    for v in d["values"]:
        t = calendar.timegm(time.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S"))
        rows.append((t, float(v["high"]), float(v["low"]), float(v["close"])))
    cache["rows"] = rows
    cache["t"] = time.time()
    return rows

def split(rows):
    return ([r[0] for r in rows], [r[1] for r in rows],
            [r[2] for r in rows], [r[3] for r in rows])

def rsi_s(c, n=14):
    out = [None]*len(c); ag = al = 0
    for i in range(1, len(c)):
        d = c[i]-c[i-1]; g = max(d, 0); l = max(-d, 0)
        if i <= n: ag += g/n; al += l/n
        else: ag = (ag*(n-1)+g)/n; al = (al*(n-1)+l)/n
        if i >= n: out[i] = 100 if al == 0 else 100-100/(1+ag/al)
    return out

def atr_s(h, l, c, n=14):
    out = [None]*len(c); a = 0
    for i in range(1, len(c)):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        if i <= n: a += tr/n
        else: a = (a*(n-1)+tr)/n
        if i >= n: out[i] = a
    return out

def ema_last(c, n):
    k = 2/(n+1); e = c[0]
    for x in c[1:]:
        e = x*k + e*(1-k)
    return e

def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"alerts": [], "last_daily": "", "last_vol": 0, "down": False}

def save(s):
    json.dump(s, open(STATE, "w"))

def status_text():
    rows = get_rows()
    ts, h, l, c = split(rows[:-1])
    R = rsi_s(c); A = atr_s(h, l, c)
    last = time.strftime("%Y-%m-%d %H:%M", time.gmtime(rows[-1][0]))
    return (f"📊 الذهب XAU/USD\nالسعر: {rows[-1][3]:.2f}\n"
            f"RSI: {R[-1]:.1f}\nATR: {A[-1]:.2f}$\n"
            f"آخر شمعة (UTC): {last}\n\n"
            "ملاحظة: إذا كان السوق مغلقاً (نهاية الأسبوع) فالسعر ثابت.")

def advice_text():
    rows = get_rows()
    ts, h, l, c = split(rows[:-1])
    R = rsi_s(c); A = atr_s(h, l, c)
    p = rows[-1][3]; r = R[-1]; a = A[-1]
    e50 = ema_last(c, 50); e200 = ema_last(c, 200)
    ch = (c[-1] - c[-17]) / a
    hi = max(h[-96:]); lo = min(l[-96:])
    pos = 100 * (p - lo) / (hi - lo) if hi > lo else 50
    avg = sum(A[-200:]) / len(A[-200:])
    if p > e50 > e200: tr = "صاعد (السعر فوق المتوسطين)"
    elif p < e50 < e200: tr = "هابط (السعر تحت المتوسطين)"
    else: tr = "مختلط أو متذبذب"
    if a > 1.3*avg: vol = "مرتفع"
    elif a < 0.7*avg: vol = "منخفض"
    else: vol = "عادي"
    t = f"🧭 الذهب XAU/USD: {p:.2f}\n\n"
    if r < 30: t += f"• RSI {r:.1f}: تشبع بيعي، الهبوط قوي وقد يرتد أو يستمر.\n"
    elif r > 70: t += f"• RSI {r:.1f}: تشبع شرائي، الصعود قوي وقد يتراجع أو يستمر.\n"
    else: t += f"• RSI {r:.1f}: محايد.\n"
    t += f"• الاتجاه: {tr}\n"
    t += f"• آخر 4 ساعات: {ch:+.1f} ATR ({'صعود' if ch > 0 else 'هبوط'})\n"
    t += f"• موقع السعر في مدى 24 ساعة: {pos:.0f}% (0 قاع، 100 قمة)\n"
    t += f"• التذبذب: {vol} (ATR = {a:.2f}$)\n"
    t += ("\nهذا وصف لحالة المؤشرات وليس توقعاً ولا توصية. "
          "اختباراتنا على 8 شهور لم تجد قاعدة بسيطة رابحة.")
    return t

def daily_text():
    rows = get_rows(0)
    ts, h, l, c = split(rows[:-1])
    A = atr_s(h, l, c)
    p = rows[-1][3]
    ch = p - c[-96]
    return (f"☀️ تقرير الذهب اليومي\nالسعر: {p:.2f}\n"
            f"تغير 24 ساعة: {ch:+.2f}$ ({100*ch/c[-96]:+.2f}%)\n"
            f"أعلى 24 ساعة: {max(h[-96:]):.2f}\nأدنى 24 ساعة: {min(l[-96:]):.2f}\n"
            f"ATR: {A[-1]:.2f}$")

def alerts_text(s):
    if not s["alerts"]:
        return "لا توجد مستويات. أضف مستوى بـ /alert 4100"
    t = "🔔 مستوياتك:\n"
    for a in s["alerts"]:
        t += f"• {a['level']:.2f} ({'عند الصعود إليه' if a['dir'] == 1 else 'عند الهبوط إليه'})\n"
    return t

def add_alert(s, args):
    if not args:
        return "اكتب المستوى، مثال: /alert 4100"
    try:
        level = float(args[0].replace(",", ""))
    except ValueError:
        return "رقم غير صالح. مثال: /alert 4100"
    if len(s["alerts"]) >= MAX_ALERTS:
        return f"الحد الأقصى {MAX_ALERTS} مستويات. احذف بعضها بـ /clear"
    p = get_rows()[-1][3]
    if abs(level - p) < 0.3:
        return f"المستوى قريب جداً من السعر الحالي ({p:.2f})."
    d = 1 if level > p else -1
    s["alerts"].append({"level": level, "dir": d, "t0": int(time.time())})
    save(s)
    return (f"✅ سأنبّهك عندما يصل السعر إلى {level:.2f} "
            f"({'صعوداً' if d == 1 else 'هبوطاً'})\nالسعر الآن: {p:.2f}")

def clear_alerts(s, args):
    if args:
        try:
            level = float(args[0])
        except ValueError:
            return "رقم غير صالح."
        n = len(s["alerts"])
        s["alerts"] = [a for a in s["alerts"] if abs(a["level"] - level) > 0.001]
        save(s)
        return "تم الحذف." if len(s["alerts"]) < n else "لم أجد هذا المستوى."
    s["alerts"] = []
    save(s)
    return "تم حذف كل المستويات."

HELP = ("الأوامر:\n/status - السعر وRSI\n/advice - شرح الوضع بالأرقام\n"
        "/alert 4100 - تنبيه عند مستوى سعر\n/alerts - عرض المستويات\n"
        "/clear - حذف كل المستويات (أو /clear 4100 لمستوى واحد)\n"
        "/daily - التقرير اليومي الآن\n/help - هذه القائمة")

def handle(cmd, args, s):
    if cmd == "/status": send(status_text())
    elif cmd == "/advice": send(advice_text())
    elif cmd == "/alert": send(add_alert(s, args))
    elif cmd == "/alerts": send(alerts_text(s))
    elif cmd == "/clear": send(clear_alerts(s, args))
    elif cmd == "/daily": send(daily_text())
    elif cmd in ("/help", "/start"): send(HELP)
    else: send("أمر غير معروف.\n" + HELP)

def market_check(s):
    rows = get_rows(0)
    if s["down"]:
        s["down"] = False
        send("✅ عادت البيانات للعمل.")
    price = rows[-1][3]
    keep = []
    for a in s["alerts"]:
        cand = [r for r in rows if r[0] >= a["t0"]]
        hi = max([r[1] for r in cand] + [price])
        lo = min([r[2] for r in cand] + [price])
        hit = hi >= a["level"] if a["dir"] == 1 else lo <= a["level"]
        if hit:
            send(f"🔔 وصل الذهب إلى {a['level']:.2f}\nالسعر الآن: {price:.2f}")
        else:
            keep.append(a)
    s["alerts"] = keep
    ts, h, l, c = split(rows[:-1])
    A = atr_s(h, l, c)
    rng = h[-1] - l[-1]
    if A[-2] and rng > VOL_MULT * A[-2] and ts[-1] > s["last_vol"]:
        s["last_vol"] = ts[-1]
        send(f"⚡ تذبذب مرتفع في الذهب\nشمعة 15 دقيقة بمدى {rng:.2f}$ "
             f"(المعتاد حوالي {A[-2]:.2f}$)\nالسعر: {price:.2f}\n"
             "الاتجاه غير محدد، فقط تنبيه بحركة قوية.")
    now = time.gmtime()
    today = time.strftime("%Y-%m-%d", now)
    if now.tm_hour >= DAILY_HOUR and s["last_daily"] != today:
        s["last_daily"] = today
        send(daily_text())
    save(s)

import threading, http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
def keepalive():
    port = int(os.environ.get("PORT", "10000"))
    http.server.HTTPServer(("0.0.0.0", port), H).serve_forever()

def main():
    threading.Thread(target=keepalive, daemon=True).start()
    s = load()
    send("▶️ بدأ مراقب الذهب (معلومات وتنبيهات)\n" + HELP)
    offset = None
    try:
        r = api("getUpdates", offset=-1, timeout=0)
        if r.get("result"): offset = r["result"][-1]["update_id"] + 1
    except Exception as e:
        print("init error:", e)
    last_check = 0; fails = 0
    while True:
        if time.time() - last_check >= EVERY:
            last_check = time.time()
            try:
                market_check(s)
                fails = 0
            except Exception as e:
                fails += 1
                print("خطأ:", e)
                if fails >= 3 and not s["down"]:
                    s["down"] = True; save(s)
                    send(f"⚠️ تعذر جلب أسعار الذهب {fails} مرات متتالية.\nالسبب: {e}")
        try:
            p = {"timeout": 20}
            if offset: p["offset"] = offset
            r = api("getUpdates", **p)
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                m = u.get("message")
                if not m or str(m["chat"]["id"]) != CHAT_ID: continue
                parts = (m.get("text") or "").strip().lower().split()
                if not parts: continue
                cmd = parts[0].split("@")[0]
                try:
                    handle(cmd, parts[1:], s)
                except Exception as e:
                    send(f"تعذر تنفيذ الأمر: {e}")
        except Exception as e:
            print("poll error:", e)
            time.sleep(5)

main()
