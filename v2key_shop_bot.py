import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import secrets
import string

# تنظیمات اصلی

BOT_TOKEN = "8295271638:AAFQtYJ9INA-cgwDYEkEldZS70W9uvgamDg"
MARZBAN_URL = "https://p.v2pro.store/admin-secure-v2-2025/#/"
MARZBAN_USERNAME = "shakib"
MARZBAN_PASSWORD = "Azadi2nafar&&"
ADMIN_IDS = [8494960799]
CHANNEL_USERNAME = "@YourChannelUsername"
CHANNEL_ID = -1001234567890

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# دیتابیس و ساخت شناسه‌ها و جداول

def init_db(db_path="vpnbot.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            phone TEXT,
            is_phone_verified INTEGER DEFAULT 0,
            is_channel_member INTEGER DEFAULT 0,
            registration_date TEXT,
            is_premium INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            wallet_balance REAL DEFAULT 0.0,
            is_banned INTEGER DEFAULT 0,
            ban_reason TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            vpn_username TEXT,
            plan_type TEXT,
            price REAL,
            expire_date TEXT,
            status TEXT DEFAULT 'active',
            created_date TEXT,
            reseller_id INTEGER,
            payment_method TEXT DEFAULT 'wallet'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            days INTEGER,
            data_limit_gb INTEGER,
            price REAL,
            reseller_price REAL,
            description TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS charge_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            payment_method TEXT,
            receipt_photo TEXT,
            status TEXT DEFAULT 'pending',
            request_date TEXT,
            admin_response TEXT,
            processed_date TEXT
        )
    """)
    # اضافه کردن پلن‌های اولیه
    cursor.execute('SELECT COUNT(*) FROM plans')
    if cursor.fetchone()[0] == 0:
        default_plans = [
            ("پلن ماهانه", 30, 50, 50000, 45000, "50 گیگ برای 30 روز"),
            ("پلن 3 ماهه", 90, 200, 120000, 110000, "200 گیگ برای 90 روز"),
            ("پلن 6 ماهه", 180, 500, 200000, 185000, "500 گیگ برای 180 روز"),
            ("پلن سالانه", 365, 1000, 350000, 320000, "1 ترابایت برای 365 روز")
        ]
        cursor.executemany("""
            INSERT INTO plans (name, days, data_limit_gb, price, reseller_price, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, default_plans)
    conn.commit()
    conn.close()

init_db()

class Database:
    def __init__(self, db_path='vpnbot.db'):
        self.db_path = db_path

    def add_user(self, user_id, username, full_name, phone=None, referred_by=None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        referral_code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name, phone, registration_date, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, full_name, phone, datetime.now().isoformat(), referral_code, referred_by))
        conn.commit()
        conn.close()

    def is_user_banned(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res and res[0] == 1

    def get_ban_reason(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT ban_reason FROM users WHERE user_id=?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res[0] if res else ""

    def ban_user(self, user_id, reason):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_banned=1, ban_reason=? WHERE user_id=?", (reason, user_id))
        conn.commit()
        conn.close()

    def unban_user(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_banned=0, ban_reason='' WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()

    def update_phone_verification(self, user_id, phone_number):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET phone=?, is_phone_verified=1 WHERE user_id=?", (phone_number, user_id))
        conn.commit()
        conn.close()

    def update_channel_membership(self, user_id, is_member=True):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_channel_member=? WHERE user_id=?", (1 if is_member else 0, user_id))
        conn.commit()
        conn.close()

    def is_user_verified(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT is_phone_verified, is_channel_member FROM users WHERE user_id=?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res and res[0] == 1 and res[1] == 1

    def get_wallet_balance(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT wallet_balance FROM users WHERE user_id=?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        return res[0] if res else 0.0

    def charge_wallet(self, user_id, amount, description="شارژ کیف پول"):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id=?", (amount, user_id))
        cursor.execute("""
            INSERT INTO wallet_transactions (user_id, type, amount, description, transaction_date)
            VALUES (?, 'charge', ?, ?, ?)
        """, (user_id, amount, description, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def deduct_wallet(self, user_id, amount, description="خرید سرویس"):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        current_balance = self.get_wallet_balance(user_id)
        if current_balance < amount:
            conn.close()
            return False
        cursor.execute("UPDATE users SET wallet_balance = wallet_balance - ? WHERE user_id=?", (amount, user_id))
        cursor.execute("""
            INSERT INTO wallet_transactions (user_id, type, amount, description, transaction_date)
            VALUES (?, 'deduct', ?, ?, ?)
        """, (user_id, -amount, description, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True

    # متدهای اضافه برای شارژ کارت به کارت، ذخیره سفارش، و ... مثل نمونه‌های قبلی

db = Database()

class MarzbanAPI:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.token = None
        self.session = requests.Session()

    async def login(self):
        resp = self.session.post(f"{self.base_url}/api/admin/token", data={
            "username": self.username,
            "password": self.password
        })
        if resp.status_code == 200:
            self.token = resp.json()["access_token"]
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
            return True
        return False

    async def create_user(self, username, expire_days=30, data_limit_gb=50):
        if not self.token:
            await self.login()
        expire_date = datetime.now() + timedelta(days=expire_days)
        data_limit_bytes = data_limit_gb * 1024 ** 3
        user_data = {
            "username": username,
            "proxies": {"vless": {}, "vmess": {}, "trojan": {}, "shadowsocks": {}},
            "expire": int(expire_date.timestamp()),
            "data_limit": data_limit_bytes,
            "data_limit_reset_strategy": "no_reset"
        }
        resp = self.session.post(f"{self.base_url}/api/user", json=user_data)
        if resp.status_code == 200:
            return resp.json()
        return None

    async def deactivate_user(self, username):
        if not self.token:
            await self.login()
        resp = self.session.delete(f"{self.base_url}/api/user/{username}")
        return resp.status_code in [200, 204]

marzban_api = MarzbanAPI(MARZBAN_URL, MARZBAN_USERNAME, MARZBAN_PASSWORD)

class ChannelManager:
    def __init__(self, bot_token=BOT_TOKEN):
        self.bot_token = bot_token

    async def check_channel_membership(self, context, user_id):
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
            return member.status in ["member", "administrator", "creator"]
        except:
            return False

    async def force_channel_join(self, update, context):
        keyboard = [
            [InlineKeyboardButton("🔗 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"عضویت در کانال {CHANNEL_USERNAME} الزامی است.\nلطفاً عضو شوید و سپس دکمه \"عضو شدم\" را بزنید."
        await update.message.reply_text(text, reply_markup=reply_markup)

channel_manager = ChannelManager()

# توابع اصلی بات در ادامه (start, handle_phone_contact, request_phone_sharing, show_main_menu و ... )

# ادمین‌ها می‌توانند کاربران را بن/آن بن کنند، شارژها را تایید یا رد کنند، و غیره

# نمونه کامند بن کردن
async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ فقط ادمین‌ها مجازند.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❗ لطفاً آیدی کاربر و دلیل بن را وارد کنید.\nمثال:\n/ban 123456789 دلیل مسدودیت")
        return
    user_id = int(context.args[0])
    reason = ' '.join(context.args[1:])
    db.ban_user(user_id, reason)
    vpn_user = db.get_vpn_username(user_id)  # متدی برای گرفتن vpn_username کاربر از orders
    if vpn_user:
        success = await marzban_api.deactivate_user(vpn_user)
        if success:
            await update.message.reply_text(f"✅ کاربر {user_id} بن شد و سرویس غیرفعال گردید.")
        else:
            await update.message.reply_text(f"⚠️ کاربر بن شد ولی غیرفعال سازی سرویس با خطا مواجه شد.")
    else:
        await update.message.reply_text(f"✅ کاربر {user_id} بن شد ولی سرویس فعالی نداشت.")
    try:
        await context.bot.send_message(user_id, f"⚠️ حساب شما توسط ادمین مسدود شد.\nدلیل: {reason}")
    except:
        pass

# ثبت هندلرها و راه‌اندازی بات به مانند نمونه‌های قبلی

def register_handlers(application):
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.CONTACT, handle_phone_contact))
    application.add_handler(CommandHandler("ban", admin_ban_user))
    # سایر هندلرها...

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    register_handlers(application)
    application.run_polling()

if __name__ == '__main__':
    main()
