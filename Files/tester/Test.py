import socket
import re
import os
import shutil
from datetime import datetime
import pytz
import jdatetime
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import binascii
import json

# مسیر پوشه پروتکل‌ها
PROTOCOL_DIR = "Splitted-By-Protocol"
# فایل‌های پروتکل
PROTOCOL_FILES = [
    "Hysteria2.txt",
    "ShadowSocks.txt",
    "Trojan.txt",
    "Vless.txt",
    "Vmess.txt"
]
# پوشه برای ذخیره نتایج
OUTPUT_DIR = "tested"
# فایل خروجی
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "config_test.txt")
# حداکثر تعداد کانفیگ موفق برای هر پروتکل
MAX_SUCCESSFUL_CONFIGS = 20
# حداکثر تعداد کانفیگ برای تست (برای کاهش زمان)
MAX_CONFIGS_TO_TEST = 100
# Timeout برای تست اتصال
TIMEOUT = 1

# ایجاد پوشه نتایج اگر وجود نداشته باشه
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# پاک کردن فایل‌های قدیمی در پوشه tested
if os.path.exists(OUTPUT_DIR):
    for file in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, file)
        if os.path.isfile(file_path):
            os.remove(file_path)

# تابع برای پاکسازی لینک کانفیگ (حذف توضیحات اضافی)
def clean_config_link(config):
    # استخراج نوع پروتکل از لینک
    protocol_match = re.match(r"^(vless|trojan|ss|hysteria2|vmess)://", config)
    if not protocol_match:
        return config  # اگر پروتکل معتبر نبود، لینک بدون تغییر برگردانده شود
    
    protocol = protocol_match.group(1)
    
    if protocol == "vmess":
        try:
            # Decode base64 برای VMess
            vmess_match = re.match(r"vmess://([A-Za-z0-9+/=]+)", config)
            if vmess_match:
                encoded_data = vmess_match.group(1)
                padding_needed = len(encoded_data) % 4
                if padding_needed:
                    encoded_data += '=' * (4 - padding_needed)
                decoded_json = base64.b64decode(encoded_data).decode('utf-8')
                vmess_obj = json.loads(decoded_json)
                # حذف توضیحات اضافی از ps (نام مستعار)
                vmess_obj['ps'] = f"server-{random.randint(1, 1000)}"  # نام ساده برای جلوگیری از توضیحات اضافی
                cleaned_json = json.dumps(vmess_obj)
                cleaned_encoded = base64.b64encode(cleaned_json.encode('utf-8')).decode('utf-8')
                return f"vmess://{cleaned_encoded}"
        except (binascii.Error, json.JSONDecodeError, ValueError):
            return config  # اگر خطایی رخ داد، لینک اصلی برگردانده شود
    else:
        # برای پروتکل‌های دیگر، لینک تا قبل از توضیحات اضافی (# غیرضروری) جدا شود
        match = re.match(r"^(vless|trojan|ss|hysteria2://[^#]+)", config)
        if match:
            return match.group(1)
        return config  # اگر الگو پیدا نشد، لینک اصلی برگردانده شود

# تابع برای استخراج نوع پروتکل از لینک
def get_protocol(config):
    protocol_match = re.match(r"^(vless|trojan|ss|hysteria2|vmess)://", config)
    return protocol_match.group(1).lower() if protocol_match else "unknown"

# تابع برای استخراج IP/دامنه و پورت از لینک پروتکل
def extract_host_port(config):
    # الگوهای قبلی برای بقیه پروتکل‌ها (بدون vmess)
    patterns = [
        r"(vless|ss|trojan|hysteria2)://.+?@(.+?):(\d+)",  # استاندارد
        r"(vless|ss|trojan|hysteria2)://(.+?):(\d+)"  # بدون uuid
    ]
    for pattern in patterns:
        match = re.match(pattern, config)
        if match:
            host = match.group(2)  # IP یا دامنه
            port = int(match.group(3))  # پورت
            return host, port
    
    # الگوی خاص برای VMess
    vmess_pattern = r"vmess://([A-Za-z0-9+/=]+)"
    vmess_match = re.match(vmess_pattern, config)
    if vmess_match:
        try:
            # Decode base64
            encoded_data = vmess_match.group(1)
            padding_needed = len(encoded_data) % 4
            if padding_needed:
                encoded_data += '=' * (4 - padding_needed)
            decoded_json = base64.b64decode(encoded_data).decode('utf-8')
            vmess_obj = json.loads(decoded_json)
            host = vmess_obj.get('add', '')  # host/address
            port = int(vmess_obj.get('port', 0))
            if host and port:
                return host, port
            else:
                print(f"خطا: هاست یا پورت در لینک VMess یافت نشد: {config[:50]}...")
        except (binascii.Error, json.JSONDecodeError, ValueError) as e:
            print(f"خطا در رمزگشایی لینک VMess: {e} - لینک: {config[:50]}...")
            return None, None
    
    print(f"خطا: لینک نامعتبر یا پروتکل پشتیبانی‌نشده: {config[:50]}...")
    return None, None

# تابع تست TCP connection و محاسبه پینگ
def test_connection_and_ping(config, timeout=TIMEOUT):
    host, port = extract_host_port(config)
    if not host or not port:
        return None
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:  # اتصال موفق
            ping_time = (time.time() - start_time) * 1000  # تبدیل به میلی‌ثانیه
            return {
                "config": config,
                "host": host,
                "port": port,
                "ping": ping_time,
                "protocol": get_protocol(config)  # پروتکل از لینک استخراج شود
            }
        return None
    except (socket.gaierror, socket.timeout):
        return None

# تاریخ و زمان برای نام‌گذاری (جلیلی، تهران)
current_date_time = jdatetime.datetime.now(pytz.timezone('Asia/Tehran'))
current_month = current_date_time.strftime("%b")
current_day = current_date_time.strftime("%d")
updated_hour = current_date_time.strftime("%H")
updated_minute = current_date_time.strftime("%M")
final_string = f"{current_month}-{current_day} | {updated_hour}:{updated_minute}"

# لیست برای ذخیره تمام کانفیگ‌های موفق
all_successful_configs = []

# پردازش هر فایل پروتکل
for protocol_file in PROTOCOL_FILES:
    file_path = os.path.join(PROTOCOL_DIR, protocol_file)
    
    # خواندن لینک‌های پروتکل از فایل
    config_links = []
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            config_links = [line.strip() for line in f if line.strip()]
    
    # انتخاب تصادفی حداکثر 100 کانفیگ برای تست
    if len(config_links) > MAX_CONFIGS_TO_TEST:
        config_links = random.sample(config_links, MAX_CONFIGS_TO_TEST)
    
    # تست موازی کانفیگ‌ها
    configs_with_ping = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_config = {executor.submit(test_connection_and_ping, config): config for config in config_links}
        for future in as_completed(future_to_config):
            result = future.result()
            if result and len(configs_with_ping) < MAX_SUCCESSFUL_CONFIGS:
                configs_with_ping.append(result)
    
    # مرتب‌سازی بر اساس پینگ و انتخاب حداکثر 20 کانفیگ
    configs_with_ping.sort(key=lambda x: x["ping"])
    successful_configs = configs_with_ping[:MAX_SUCCESSFUL_CONFIGS]
    
    # اضافه کردن به لیست کلی
    all_successful_configs.extend(successful_configs)

# ذخیره تمام کانفیگ‌های موفق در یک فایل
if all_successful_configs:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(f"#🌐 به روزرسانی شده در {final_string} | MTSRVRS\n")
        for i, result in enumerate(all_successful_configs, 1):
            # پاکسازی لینک کانفیگ
            cleaned_config = clean_config_link(result['config'])
            config_string = f"#🌐سرور {i} | {result['protocol']} | {final_string} | Ping: {result['ping']:.2f}ms"
            file.write(f"{cleaned_config}{config_string}\n")
    print(f"All results saved to {OUTPUT_FILE}")
else:
    print("No successful configs found for any protocol")
