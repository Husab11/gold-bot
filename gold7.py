import requests, time, os, calendar, threading, http.server
from config import TOKEN, CHAT_ID, TD_KEY

CHAT_ID = str(CHAT_ID)
DAILY_HOUR = 8
EVERY = 180
SIG_EVERY = 1800
N, SL_ATR, RR, COST, MAXBARS = 20, 1.5, 2, 0.5, 30
VOL_MULT = 3.0
MAX_ALERTS = 10
API = f"https://api.telegram.org/bot{TOKEN}/"
S = {"alerts": [], "offset": float(os.environ.get("OFFSET", "0")),
     "last_daily": "", "last_vol": 0, "down": False,
     "open": None, "last_sig": 0, "n": 0, "wins": 0, "total": 0.0}
cache = {}

def api(method, **p):
    return requests.post(API + method, data=p, timeout=40).json()

def send(msg):
    print(msg)
    try:
        api("sendMessage", chat_id=CHAT_ID, text=msg)
    except Exception as e:
        print("telegram error:", e)

def td(endpoint, **p):
    p["apikey"] = TD_KEY
    d = requests.get("https://api.twelvedata.com/" + endpoint, params=p, timeout=20).json()
    if d.get("status") == "error":
        raise Exception(d.get("message", "twelvedata error"))
    return d

def candles(iv, size, maxage):
    k = (iv, size)
    c = cache.get(k)
    if c and time.time() - c[0] < maxage:
        return c[1]
    d = td("time_series", symbol="XAU/USD", interval=iv, outputsize=size,
           order="ASC", timezone="UTC")
    rows = []
    for v in d["values"]:
        dt = v["datetime"]
        fmt = "%Y-%m-%d" if len(dt) == 10 else "%Y-%m-%d %H:%M:%S"
        t = calendar.timegm(time.strptime(dt[:19], fmt))
        rows.append((t, float(v["high"]), float(v["low"]), float(v["close"])))
    cache[k] = (time.time(), rows)
    return rows

def raw_price():
    return float(td("price", symbol="XAU/USD")["price"])

def price():
    return raw_price() + S["offset"]

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

def open_text():
    t = S["open"]
    o = S["offset"]
    return (f"{'شراء' if t['side'] == 1 else 'بيع'} | الدخول {t['entry']+o:.2f} | "
            f"الوقف {t['sl']+o:.2f} | الهدف {t['tp']+o:.2f}")

def status_text():
    p = price()
    rows = candles("15min", 300, 900)[:-1]
    ts, h, l, c = split(rows)
    R = rsi_s(c); A = atr_s(h, l, c)
    t = f"📊 الذهب XAU/USD\nالسعر: {p:.2f}"
    if S["offset"]: t += f" (شامل فرق {S['offset']:+.2f})"
    t += f"\nRSI: {R[-1]:.1f}\nATR: {A[-1]:.2f}$\n"
    if S["open"]: t += f"\n📌 إشارة 4 ساعات مفتوحة:\n{open_text()}\n"
    t += "\nالسعر من مصدر مجاني وقد يختلف عن منصتك. معلومات وليست توصية."
    return t

def advice_text():
    praw = raw_price()
    rows = candles("15min", 300, 900)[:-1]
    ts, h, l, c = split(rows)
    R = rsi_s(c); A = atr_s(h, l, c)
    r = R[-1]; a = A[-1]
    e50 = ema_last(c, 50); e200 = ema_last(c, 200)
    ch = (praw - c[-17]) / a
    hi = max(h[-96:]); lo = min(l[-96:])
    pos = 100 * (praw - lo) / (hi - lo) if hi > lo else 50
    avg = sum(A[-200:]) / len(A[-200:])
    if praw > e50 > e200: tr = "صاعد (السعر فوق المتوسطين)"
    elif praw < e50 < e200: tr = "هابط (السعر تحت المتوسطين)"
    else: tr = "مختلط أو متذبذب"
    vol = "مرتفع" if a > 1.3*avg else "منخفض" if a < 0.7*avg else "عادي"
    t = f"🧭 الذهب: {praw + S['offset']:.2f}\n\n"
    if r < 30: t += f"• RSI {r:.1f}: تشبع بيعي.\n"
    elif r > 70: t += f"• RSI {r:.1f}: تشبع شرائي.\n"
    else: t += f"• RSI {r:.1f}: محايد.\n"
    t += f"• الاتجاه: {tr}\n"
    t += f"• آخر 4 ساعات: {ch:+.1f} ATR\n"
    t += f"• موقع السعر في مدى 24 ساعة: {pos:.0f}%\n"
    t += f"• التذبذب: {vol} (ATR = {a:.2f}$)\n"
    t += "\nوصف للمؤشرات وليس توقعاً ولا توصية."
    return t

def daily_text():
    p = price()
    rows = candles("15min", 300, 900)[:-1]
    ts, h, l, c = split(rows)
    A = atr_s(h, l, c); o = S["offset"]
    ch = p - (c[-96] + o)
    return (f"☀️ تقرير الذهب اليومي\nالسعر: {p:.2f}\n"
            f"تغير 24 ساعة: {ch:+.2f}$\n"
            f"أعلى 24 ساعة: {max(h[-96:])+o:.2f}\nأدنى 24 ساعة: {min(l[-96:])+o:.2f}\n"
            f"ATR: {A[-1]:.2f}$")

def levels_text():
    p = price(); o = S["offset"]
    d = candles("1day", 10, 1800)
    today = d[-1]; yest = d[-2]; wk = d[-6:-1]
    lo50 = int(p // 50) * 50
    lo100 = int(p // 100) * 100
    return (f"📍 مستويات الذهب (السعر {p:.2f})\n"
            f"اليوم: أعلى {today[1]+o:.2f} | أدنى {today[2]+o:.2f}\n"
            f"أمس: أعلى {yest[1]+o:.2f} | أدنى {yest[2]+o:.2f}\n"
            f"آخر 5 أيام: أعلى {max(x[1] for x in wk)+o:.2f} | أدنى {min(x[2] for x in wk)+o:.2f}\n"
            f"أرقام مستديرة: {lo50} / {lo50+50} | {lo100} / {lo100+100}")

def size_text(args):
    try:
        bal, pct, dist = [float(x) for x in args[:3]]
        if bal <= 0 or pct <= 0 or dist <= 0: raise ValueError
    except Exception:
        return "الصيغة: /size الرصيد النسبة% مسافة_الوقف$\nمثال: /size 1000 1 6"
    risk = bal * pct / 100
    lots = int(risk / (dist * 100) * 100) / 100
    return (f"🧮 المخاطرة: ${risk:.2f}\nالحجم المقترح: {lots:.2f} لوت\n"
            "(على أساس 1 لوت = 100 أونصة، تأكد من مواصفات وسيطك. "
            "إن كان الحجم 0.00 فالمخاطرة صغيرة جداً لهذه المسافة.)")

def alerts_text():
    if not S["alerts"]:
        return "لا توجد مستويات. أضف مستوى بـ /alert 4100"
    t = "🔔 مستوياتك:\n"
    for a in S["alerts"]:
        t += f"• {a['level']:.2f} ({'صعوداً' if a['dir'] == 1 else 'هبوطاً'})\n"
    return t

def add_alert(args):
    if not args: return "مثال: /alert 4100"
    try: level = float(args[0].replace(",", ""))
    except ValueError: return "رقم غير صالح. مثال: /alert 4100"
    if len(S["alerts"]) >= MAX_ALERTS:
        return f"الحد الأقصى {MAX_ALERTS}. احذف بعضها بـ /clear"
    p = price()
    if abs(level - p) < 0.3: return f"المستوى قريب جداً من السعر ({p:.2f})."
    d = 1 if level > p else -1
    S["alerts"].append({"level": level, "dir": d})
    return f"✅ سأنبّهك عند {level:.2f} ({'صعوداً' if d == 1 else 'هبوطاً'})\nالسعر الآن: {p:.2f}"

def clear_alerts(args):
    if args:
        try: level = float(args[0])
        except ValueError: return "رقم غير صالح."
        n = len(S["alerts"])
        S["alerts"] = [a for a in S["alerts"] if abs(a["level"] - level) > 0.001]
        return "تم الحذف." if len(S["alerts"]) < n else "لم أجد هذا المستوى."
    S["alerts"] = []
    return "تم حذف كل المستويات."

def offset_cmd(args):
    if not args:
        return (f"الفرق الحالي: {S['offset']:+.2f}\nلتغييره: /offset 2\n"
                "ضع نفس القيمة في متغير OFFSET في Render لتبقى بعد إعادة التشغيل.")
    try: S["offset"] = float(args[0])
    except ValueError: return "رقم غير صالح."
    return (f"✅ الفرق الآن {S['offset']:+.2f}\n"
            "المستويات المسجلة سابقاً لم تتغير، احذفها بـ /clear وأعد إضافتها.")

def stats_text():
    t = "📈 إشارات كسر 4 ساعات (تجربة أمامية)\n"
    if S["n"] == 0: t += "لا توجد إشارات مغلقة بعد.\n"
    else:
        t += (f"الصفقات: {S['n']} | نجاح {100*S['wins']/S['n']:.0f}%\n"
              f"الإجمالي: {S['total']:+.1f}R | المتوسط {S['total']/S['n']:+.2f}R\n")
    if S["open"]: t += f"\n📌 مفتوحة:\n{open_text()}\n"
    t += "\nالإحصائيات تضيع عند إعادة تشغيل Render، فالسجل الدائم هو رسائل هذه المحادثة."
    return t

HELP = ("الأوامر:\n/status - السعر وRSI\n/advice - شرح الوضع بالأرقام\n"
        "/levels - مستويات السعر\n/size 1000 1 6 - حجم الصفقة\n"
        "/alert 4100 - تنبيه عند مستوى\n/alerts - عرض المستويات\n"
        "/clear - حذف المستويات\n/offset 2 - معايرة فرق منصتك\n"
        "/stats - إشارات 4 ساعات\n/daily - التقرير اليومي\n/help - القائمة")

def handle(cmd, args):
    if cmd == "/status": send(status_text())
    elif cmd == "/advice": send(advice_text())
    elif cmd == "/levels": send(levels_text())
    elif cmd == "/size": send(size_text(args))
    elif cmd == "/alert": send(add_alert(args))
    elif cmd == "/alerts": send(alerts_text())
    elif cmd == "/clear": send(clear_alerts(args))
    elif cmd == "/offset": send(offset_cmd(args))
    elif cmd == "/stats": send(stats_text())
    elif cmd == "/daily": send(daily_text())
    elif cmd in ("/help", "/start"): send(HELP)
    else: send("أمر غير معروف.\n" + HELP)

def track_open(rows):
    t = S["open"]
    if not t: return
    side = t["side"]; out = None
    bars = [r for r in rows if r[0] > t["ts"]]
    for k, (ts, h, l, c) in enumerate(bars):
        hs = l <= t["sl"] if side == 1 else h >= t["sl"]
        ht = h >= t["tp"] if side == 1 else l <= t["tp"]
        if hs: out = -1.0; why = "وقف الخسارة"; break
        if ht: out = float(RR); why = "الهدف"; break
        if k + 1 >= MAXBARS:
            out = side*(c - t["entry"])/t["risk"]; why = "انتهاء المدة"; break
    if out is None: return
    out -= COST / t["risk"]
    S["n"] += 1; S["wins"] += out > 0; S["total"] += out; S["open"] = None
    send(f"{'✅' if out > 0 else '❌'} أُغلقت إشارة 4 ساعات ({why})\n"
         f"النتيجة: {out:+.2f}R\n"
         f"الإجمالي: {S['total']:+.1f}R | إشارات {S['n']} | نجاح {100*S['wins']/S['n']:.0f}%")

def signal_check():
    rows = candles("4h", 120, 0)[:-1]
    if len(rows) < N + 20: return
    ts, h, l, c = split(rows)
    if S["last_sig"] == 0:
        S["last_sig"] = ts[-1]
        return
    track_open(rows)
    if S["open"] or ts[-1] <= S["last_sig"]: return
    A = atr_s(h, l, c); i = len(c) - 1
    side = 0
    if c[i] > max(h[i-N:i]): side = 1
    elif c[i] < min(l[i-N:i]): side = -1
    if not side: return
    entry = c[i]; risk = SL_ATR * A[i]
    sl = entry - side*risk; tp = entry + side*risk*RR
    S["open"] = {"ts": ts[i], "side": side, "entry": entry, "sl": sl, "tp": tp, "risk": risk}
    S["last_sig"] = ts[i]
    o = S["offset"]
    send(f"{'🟢 كسر صاعد' if side == 1 else '🔴 كسر هابط'} على 4 ساعات - الذهب\n"
         f"الدخول: {entry+o:.2f}\nالوقف: {sl+o:.2f}\nالهدف: {tp+o:.2f}\n"
         f"المسافة للوقف: {risk:.2f}$ (استخدم /size)\n\n"
         "⚠️ فكرة غير مثبتة: نتيجتها في الاختبار التاريخي كانت إيجابية في آخر سنتين فقط. "
         "تجربة أمامية، نفّذها على Demo فقط.")

def market_check():
    p = price()
    if S["down"]:
        S["down"] = False
        send("✅ عادت البيانات للعمل.")
    keep = []
    for a in S["alerts"]:
        hit = p >= a["level"] if a["dir"] == 1 else p <= a["level"]
        if hit: send(f"🔔 وصل الذهب إلى {a['level']:.2f}\nالسعر الآن: {p:.2f}")
        else: keep.append(a)
    S["alerts"] = keep
    rows = candles("15min", 300, 900)[:-1]
    ts, h, l, c = split(rows)
    A = atr_s(h, l, c); rng = h[-1] - l[-1]
    if A[-2] and rng > VOL_MULT * A[-2] and ts[-1] > S["last_vol"]:
        S["last_vol"] = ts[-1]
        send(f"⚡ تذبذب مرتفع في الذهب\nشمعة 15 دقيقة بمدى {rng:.2f}$ "
             f"(المعتاد {A[-2]:.2f}$)\nالسعر: {p:.2f}\nالاتجاه غير محدد.")
    now = time.gmtime()
    today = time.strftime("%Y-%m-%d", now)
    if now.tm_hour >= DAILY_HOUR and S["last_daily"] != today:
        S["last_daily"] = today
        send(daily_text())

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
    send("▶️ بدأ مراقب الذهب (النسخة 7)\n" + HELP)
    offset = None
    try:
        r = api("getUpdates", offset=-1, timeout=0)
        if r.get("result"): offset = r["result"][-1]["update_id"] + 1
    except Exception as e:
        print("init error:", e)
    last_m = 0; last_s = 0; fails = 0
    while True:
        if time.time() - last_m >= EVERY:
            last_m = time.time()
            try:
                market_check(); fails = 0
            except Exception as e:
                fails += 1; print("خطأ:", e)
                if fails >= 3 and not S["down"]:
                    S["down"] = True
                    send(f"⚠️ تعذر جلب أسعار الذهب {fails} مرات متتالية.\nالسبب: {e}")
        if time.time() - last_s >= SIG_EVERY:
            last_s = time.time()
            try: signal_check()
            except Exception as e: print("signal error:", e)
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
                try: handle(parts[0].split("@")[0], parts[1:])
                except Exception as e: send(f"تعذر تنفيذ الأمر: {e}")
        except Exception as e:
            print("poll error:", e)
            time.sleep(5)

main()
