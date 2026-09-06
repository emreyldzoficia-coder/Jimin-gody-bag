import os
import json
import asyncio
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import requests
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Render Ortam Değişkenleri
TELEGRAM_BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()
MIN_COINS = int((os.getenv("MIN_COINS") or "5").strip())

UPSTASH_URL = (os.getenv("UPSTASH_REDIS_REST_URL") or "").strip().rstrip("/")
UPSTASH_TOKEN = (os.getenv("UPSTASH_REDIS_REST_TOKEN") or "").strip()

BASE_URL = "https://dichvu321.com"
PAGE_URL = f"{BASE_URL}/en/tiktok-treasure-box-bot/"
PROXY_URL = f"{BASE_URL}/proxy.php"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Origin": BASE_URL,
    "Referer": PAGE_URL,
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin"
}

LOCAL_KEYS = set()

# Render Web Service ve UptimeRobot kontrolü için HTTP sunucu
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_dummy_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def is_seen(key):
    if key in LOCAL_KEYS:
        return True

    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            req_url = f"{UPSTASH_URL}/set/{key}/1/nx/ex/86400"
            headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
            res = requests.get(req_url, headers=headers, timeout=3).json()
            if res.get("result") is None:
                return True
        except Exception as e:
            logging.error(f"Redis Hatası: {e}")

    LOCAL_KEYS.add(key)
    if len(LOCAL_KEYS) > 10000:
        LOCAL_KEYS.clear()
    return False

def send_telegram(mesaj):
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mesaj,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logging.error(f"Telegram Hatası: {e}")

def get_ticket(session):
    session.get(PAGE_URL, headers=BROWSER_HEADERS, timeout=10)
    params = {
        "transport": "ws",
        "mode": "bootstrap",
        "stream": "all",
        "live": "30000"
    }
    res = session.post(PROXY_URL, params=params, headers=FETCH_HEADERS, timeout=10)
    try:
        data = res.json()
        if data.get("success") and "path" in data:
            return data["path"], session.cookies.get_dict()
    except Exception as e:
        logging.error(f"Bilet Ayrıştırma Hatası: {e}")
    return None, None

async def connect_ws(ws_url, ws_headers):
    try:
        return await websockets.connect(ws_url, additional_headers=ws_headers, ping_interval=20, ping_timeout=20)
    except TypeError:
        try:
            return await websockets.connect(ws_url, extra_headers=ws_headers, ping_interval=20, ping_timeout=20)
        except TypeError:
            return await websockets.connect(ws_url, ping_interval=20, ping_timeout=20)

async def run_bot():
    send_telegram("🎁 <b>Özel Goody Bag Radarı Aktif!</b>\nSadece hediye çantaları taranıyor...")
    session = requests.Session()

    while True:
        try:
            logging.info("🎫 Bilet talep ediliyor...")
            path, cookies = await asyncio.to_thread(get_ticket, session)

            if not path:
                logging.warning("⚠️ Bilet alınamadı, 4 saniye sonra tekrar deneniyor...")
                await asyncio.sleep(4)
                continue

            ws_url = f"wss://dichvu321.com{path}"
            logging.info("🎯 Bilet alındı, WebSocket bağlanıyor...")

            cookie_header = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            ws_headers = {
                "User-Agent": BROWSER_HEADERS["User-Agent"],
                "Origin": BASE_URL,
                "Cookie": cookie_header
            }

            ws = await connect_ws(ws_url, ws_headers)
            async with ws:
                logging.info("✅ Canlı WebSocket bağlı! Sadece Goody Bag'ler taranıyor...")
                while True:
                    msg = await ws.recv()
                    try:
                        raw = json.loads(msg)
                        msg_type = raw.get("type")

                        if msg_type == "ready":
                            covered = raw.get("data", {}).get("coveredLive", 0)
                            logging.info(f"💓 Aktif Dinlenen Canlı Yayın: {covered}")
                            continue

                        if msg_type == "demoEvents" and isinstance(raw.get("events"), list):
                            for item in raw["events"]:
                                event_type = item.get("type", "box")

                                # SADECE GOODY BAG FİLTRESİ: Farklı bir tipse atla
                                if event_type != "goody_bag":
                                    continue

                                username = item.get("uniqueId")
                                if not username:
                                    continue

                                coins = int(item.get("coins") or 0)
                                if coins < MIN_COINS:
                                    continue

                                timestamp = item.get("timestamp", 0)
                                key = f"goody:{username}:{coins}:{timestamp}"

                                if is_seen(key):
                                    continue

                                can_open = item.get("canOpen", 0)
                                viewers = item.get("viewerCount", 0)
                                level = item.get("level", 0)

                                box_name = f"🎁 GOODY BAG (Lvl {level})"
                                live_link = f"https://www.tiktok.com/@{username}/live"
                                viewers_str = f"👁️ <b>İzleyici:</b> {viewers}\n" if viewers else ""
                                people_str = f"👥 <b>Kişi Sayısı:</b> {can_open}\n" if can_open else ""

                                mesaj = (
                                    f"✨ <b>{box_name}</b>\n\n"
                                    f"👤 <b>Yayıncı:</b> @{username}\n"
                                    f"💎 <b>Coin:</b> {coins}\n"
                                    f"{people_str}"
                                    f"{viewers_str}\n"
                                    f"⚡ <a href='{live_link}'>YAYINA GİT</a>"
                                )
                                send_telegram(mesaj)
                                logging.info(f"🎁 GOODY BAG İLETİLDİ: @{username} ({coins} Coin)")

                    except Exception as err:
                        logging.error(f"Ayrıştırma hatası: {err}")

        except Exception as e:
            logging.error(f"Soket döngüsü koptu: {e}")
            await asyncio.sleep(3)

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    asyncio.run(run_bot())
