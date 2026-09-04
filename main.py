import os
import asyncio
import json
import time
import requests
import websockets
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# Render/UptimeRobot Kapanma Engelleyici (Dummy Server)
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Goody Bot Active!")

    def log_message(self, format, *args):
        pass

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()

# Telegram Ayarları (Gizli bilgiler Render ortam değişkenlerinden çekilir)
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PROXY_URL = "https://dichvu321.com/proxy.php?stream=all&live=4000"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36",
    "Origin": "https://dichvu321.com",
    "Referer": "https://dichvu321.com/"
}

http_session = requests.Session()
LOCAL_CACHE = set()

def to_int(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        number = int(value)
        if 0 <= number <= 100000:
            return number
    except Exception:
        pass
    return None

def format_duration(seconds):
    """Saniyeyi Dakika ve Saniyeye çevirir"""
    if seconds <= 0:
        return "Bilinmiyor"
    
    minutes = seconds // 60
    remaining_sec = seconds % 60
    
    if minutes > 0 and remaining_sec > 0:
        return f"{minutes} Dakika {remaining_sec} Saniye"
    elif minutes > 0:
        return f"{minutes} Dakika"
    else:
        return f"{remaining_sec} Saniye"

def recursive_find_key(obj, wanted_keys, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_normalized = str(key).lower().replace("_", "").replace("-", "")
            current_path = f"{path}.{key}" if path else str(key)
            if key_normalized in wanted_keys:
                number = to_int(value)
                if number is not None:
                    return number, current_path
            result = recursive_find_key(value, wanted_keys, current_path)
            if result[0] is not None:
                return result
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            result = recursive_find_key(item, wanted_keys, f"{path}[{index}]")
            if result[0] is not None:
                return result
    return None, None

def find_box_level(payload, envelope_info):
    level_keys = ["boxlevel", "chestlevel", "envelopelevel", "level", "grade", "rank"]
    for key in level_keys:
        val = envelope_info.get(key) or payload.get(key)
        if val is not None:
            num = to_int(val)
            if num is not None and 1 <= num <= 20:
                return num
    
    for key in level_keys:
        value, _ = recursive_find_key(payload, [key])
        if value is not None and 1 <= value <= 20:
            return value
            
    return 1

def get_chest_recipients(payload):
    key_groups = [
        ["canopen"], ["peoplecount"], ["participantcount"], ["winnercount"],
        ["claimcount"], ["recipientcount"], ["grabcount"], ["membercount"],
        ["people"], ["participants"], ["winners"], ["recipients"]
    ]
    for wanted_keys in key_groups:
        value, path = recursive_find_key(payload, wanted_keys)
        if value is not None:
            return value, path
    return None, None

async def send_telegram(mesaj):
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        print("⚠️ Telegram token veya Chat ID eksik!")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mesaj,
        "disable_web_page_preview": True
    }
    try:
        await asyncio.to_thread(http_session.post, url, json=payload, timeout=2)
    except Exception:
        pass

async def listen_live_feed():
    while True:
        try:
            res = await asyncio.to_thread(http_session.get, PROXY_URL, headers=HEADERS, timeout=5)
            data = res.json()

            if data.get("success"):
                path = data.get("path")
                ws_url = f"wss://dichvu321.com{path}"

                async with websockets.connect(
                    ws_url,
                    additional_headers=HEADERS,
                    ping_interval=20,
                    ping_timeout=10
                ) as websocket:

                    async for message in websocket:
                        try:
                            event_data = json.loads(message)
                        except Exception:
                            continue

                        payload = (
                            event_data.get("data")
                            if isinstance(event_data.get("data"), dict)
                            else event_data
                        )

                        if not isinstance(payload, dict) or payload.get("status") == "connected":
                            continue

                        box_type_raw = str(payload.get("type") or "").lower()
                        source_raw = str(payload.get("source") or "").lower()
                        envelope_info = payload.get("envelopeInfo") or {}

                        if not isinstance(envelope_info, dict):
                            envelope_info = {}

                        business_type = envelope_info.get("businessType", 1)
                        
                        # Goody Bag Filtresi
                        is_goody = (business_type == 2 or "goody" in box_type_raw or "goody" in source_raw)
                        if not is_goody:
                            continue

                        # Gerçek Toplam Elmas Sayısı
                        coins = int(
                            envelope_info.get("totalDiamondCount")
                            or envelope_info.get("diamondCount")
                            or envelope_info.get("coinCount")
                            or payload.get("totalCoins")
                            or payload.get("coins")
                            or payload.get("diamondCount")
                            or 0
                        )

                        # 50 Elmasın Altındaki Kutuları Atla
                        if coins < 50:
                            continue

                        username = (
                            payload.get("uniqueId")
                            or payload.get("nickname")
                            or payload.get("username")
                            or ""
                        )
                        clean_username = str(username).replace("@", "").strip().lower()

                        if not clean_username or clean_username in LOCAL_CACHE:
                            continue

                        LOCAL_CACHE.add(clean_username)

                        # Kutu Seviyesi
                        box_level = find_box_level(payload, envelope_info)

                        # Dağıtılan Kişi Sayısı
                        recipients, _ = get_chest_recipients(payload)
                        recipients_text = f"{recipients}" if recipients is not None else "Belirtilmemiş"

                        # İzleyici Sayısı
                        viewers = (
                            payload.get("viewerCount")
                            or payload.get("userCount")
                            or envelope_info.get("viewerCount")
                            or 0
                        )

                        # Geri Sayım Süresi
                        raw_time = (
                            envelope_info.get("unpackAt")
                            or envelope_info.get("unpackTime")
                            or payload.get("delay")
                            or payload.get("displayDuration")
                            or 0
                        )
                        
                        now_ts = int(time.time())
                        if raw_time > 1000000000:
                            remaining = raw_time - now_ts
                            duration_text = format_duration(remaining) if 0 < remaining < 3600 else "Bilinmiyor"
                        elif raw_time > 0:
                            duration_text = format_duration(raw_time)
                        else:
                            duration_text = "Bilinmiyor"

                        live_link = f"https://www.tiktok.com/@{clean_username}/live"

                        # Görev Satırı Olmayan Mesaj Formatı
                        mesaj_satirlari = [
                            f"🎁 GOODY BAG 🏅 Lvl {box_level}",
                            f"👤 YAYINCI: @{clean_username}",
                            f"💎 ELMAS: {coins}",
                            f"👥 KAZANAN: {recipients_text} | 👀 {viewers}",
                            f"⏱️ SÜRE: {duration_text}",
                            f"⚡ {live_link}"
                        ]

                        mesaj = "\n".join(mesaj_satirlari)

                        asyncio.create_task(send_telegram(mesaj))
                        print(f"GOODY: @{clean_username} | Elmas: {coins}")

        except Exception as e:
            print(f"Bağlantı hatası: {e}")
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    Thread(target=run_dummy_server, daemon=True).start()
    asyncio.run(listen_live_feed())
