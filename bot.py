import threading
from bit import Key
import requests
import time
import datetime
import os
import psutil
from flask import Flask, send_from_directory
import signal
import sys
import queue

# --- Settings ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PORT = int(os.getenv("PORT", 10000))
START_TIME = time.time()

# --- Flask app ---
app = Flask(__name__, static_folder='static')

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

def flask_thread():
    app.run(host='0.0.0.0', port=PORT)

# --- Telegram messaging with retry ---
def send_telegram_message(bot_token, chat_id, message, retries=5):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    for i in range(retries):
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                return True
            else:
                print(f"[!] Telegram Send failed {res.status_code}: {res.text} - Message: {message}")
        except Exception as e:
            print(f"[!] Telegram Send Exception: {e}")
        time.sleep(2 ** i)
    return False

# --- Load target addresses ---
def load_target_addresses(filename):
    with open(filename, 'r') as f:
        return set(line.strip() for line in f if line.strip())

# --- Generate only 1 and bc1 addresses ---
def generate_addresses(key):
    addresses = [key.address, key.segwit_address]
    return [addr for addr in addresses if addr.startswith('1') or addr.startswith('bc1')]

# --- Format Match Found message (حذف نوشتن به فایل) ---
def format_match_message(address, private_key):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    # حذف لاگ به فایل matches.log
    return (
        f"🚨 *MATCH FOUND!* 🚨\n\n"
        f"🔑 *Address:*  \n`{address}`\n\n"
        f"🔐 *Private Key (WIF):*  \n`{private_key}`\n\n"
        f"⚠️ **لطفاً کلید خصوصی را با دقت نگهداری کنید و آن را به کسی ندهید!**\n\n"
        f"---\n\n"
        f"⏰ _زمان یافتن:_ {now}\n\n"
        f"🔗 [بررسی تراکنش‌ها](https://www.blockchain.com/btc/address/{address})"
    )

# --- Format 6-hour report message ---
def format_report_message(count, uptime, cpu, ram):
    thread_count = threading.active_count()
    return (
        f"🕒 *6-hour Report*\n\n"
        f"🔢 *Addresses Checked:* `{count}`\n"
        f"⏱ *Uptime:* `{uptime}`\n"
        f"🖥 *CPU Usage:* `{cpu}%`\n"
        f"💾 *RAM Usage:* `{ram}%`\n"
        f"🔄 *Active Threads:* `{thread_count}`"
    )

# --- Worker thread to check keys ---
def worker_thread(targets, queue, counter):
    while True:
        key = Key()
        addrs = generate_addresses(key)
        for addr in addrs:
            if addr in targets:
                print(f"[MATCH] {addr}")
                queue.put(format_match_message(addr, key.to_wif()))
        with counter_lock:
            counter[0] += 1

# --- Listener thread for matches ---
def listener_thread(queue, token, channel):
    while True:
        try:
            msg = queue.get()
            if msg == 'STOP':
                break
            send_telegram_message(token, channel, msg)
        except Exception as e:
            print(f"[Listener Exception] {e}")

# --- Periodic report to Telegram ---
def reporter_thread(counter, token, channel):
    while True:
        time.sleep(21600)  # 6 ساعت
        count = counter[0]
        uptime = str(datetime.timedelta(seconds=int(time.time() - START_TIME)))
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        msg = format_report_message(count, uptime, cpu, ram)
        send_telegram_message(token, channel, msg)

# --- Signal handler ---
def signal_handler(sig, frame):
    print("[!] Signal received, shutting down...")
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not BOT_TOKEN or not CHANNEL_ID:
        print("[!] BOT_TOKEN or CHANNEL_ID is not set.")
        sys.exit(1)

    send_telegram_message(BOT_TOKEN, CHANNEL_ID, "🚀 Bot is starting...")

    threading.Thread(target=flask_thread, daemon=True).start()

    targets = load_target_addresses('add.txt')
    print(f"[+] Loaded {len(targets)} target addresses.")

    q = queue.Queue()
    counter = [0]
    counter_lock = threading.Lock()

    # Listener and Reporter threads
    threading.Thread(target=listener_thread, args=(q, BOT_TOKEN, CHANNEL_ID), daemon=True).start()
    threading.Thread(target=reporter_thread, args=(counter, BOT_TOKEN, CHANNEL_ID), daemon=True).start()

    # Worker threads
    num_workers = max(1, os.cpu_count() - 1)
    for _ in range(num_workers):
        threading.Thread(target=worker_thread, args=(targets, q, counter), daemon=True).start()

    while True:
        time.sleep(60)
