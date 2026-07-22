import time
import json
import hashlib
from urllib.parse import quote
from Crypto.Cipher import AES
import base64
import requests
import random


class RateLimitError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


DEFAULT_APP_ID = "ak_HTg6gVlvTRMyi"
DEFAULT_APP_SECRET = "c4tXXNpzvNlDilB8NY8lpg=="
DEFAULT_BASE_DOMAIN = "http://81.71.22.199:8083"

# ==================== 频率控制配置（可自行修改） ====================
MIN_INTERVAL = 2          # 单店铺请求间隔（秒）；文档要求单店铺至少间隔 1 秒，这里留一点余量
MAX_INTERVAL = 10         # 发生限频后放慢到的最大请求间隔（秒）
MAX_RETRIES = 3           # 网络异常的最大重试次数；限流不在客户端内部长时间重试
# ===================================================================


class LingXingClient:
    def __init__(self, app_id=DEFAULT_APP_ID, app_secret=DEFAULT_APP_SECRET, base_domain=DEFAULT_BASE_DOMAIN):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_domain = base_domain.rstrip("/")
        self.access_token = None
        self.refresh_token = None
        self.token_expire_time = 0
        self.token_url = f"{self.base_domain}/api/auth-server/oauth/access-token"
        self.last_request_time = 0
        self.min_interval = MIN_INTERVAL
        self._current_interval = MIN_INTERVAL
        self._backoff_until = 0

    def _get_timestamp(self):
        return int(time.time())

    def _is_token_expired(self):
        if not self.access_token or not self.token_expire_time:
            return True
        return self._get_timestamp() >= (self.token_expire_time - 60)

    def _get_access_token(self, use_refresh=False):
        data = {'refresh_token': self.refresh_token} if use_refresh else {
            'appId': self.app_id, 'appSecret': self.app_secret}
        resp = requests.post(self.token_url, data=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if str(result.get('code')) == '200':
            data_obj = result.get('data', {})
            self.access_token = data_obj.get('access_token')
            self.refresh_token = data_obj.get('refresh_token')
            expires_in = int(data_obj.get('expires_in', 0))
            self.token_expire_time = self._get_timestamp() + expires_in
            return self.access_token
        else:
            raise Exception(f"获取token失败: {result.get('msg')} (code: {result.get('code')})")

    def _ensure_valid_token(self):
        if not self._is_token_expired():
            return self.access_token
        if self.refresh_token:
            try:
                return self._get_access_token(use_refresh=True)
            except Exception:
                pass
        return self._get_access_token(use_refresh=False)

    def _rate_limit(self):
        now = time.time()
        # 如果处于退避期，强制使用较长的间隔
        interval = self._current_interval
        if now < self._backoff_until:
            interval = max(interval, MAX_INTERVAL)
        elapsed = now - self.last_request_time
        if elapsed < interval:
            time.sleep(interval - elapsed + random.uniform(0.5, 1.5))
        self.last_request_time = time.time()

    def _request_with_retry(self, method, url, **kwargs):
        """带退避重试的请求；限流快速抛出，交给业务层缓存后置处理。"""
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = requests.request(method, url, **kwargs)
                resp.raise_for_status()
                result = resp.json()
                code = str(result.get('code'))
                if code in ['0', '200']:
                    # 成功且不在退避期，慢慢恢复速度
                    if time.time() >= self._backoff_until and self._current_interval > self.min_interval:
                        self._current_interval = max(self.min_interval, self._current_interval - 0.5)
                    return result
                # 频率限制不在这里长时间 sleep，避免单个批次卡死整轮请求。
                if code in ['103', '3001008']:
                    self._current_interval = min(self._current_interval + 3, MAX_INTERVAL)
                    self._backoff_until = 0
                    message = result.get('msg') or result.get('message') or '请求过于频繁'
                    raise RateLimitError(f"{message} (code: {code})", code=code)
                # 其他业务错误直接抛
                raise Exception(f"请求失败: {result.get('msg')} (code: {code})")
            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    wait = 5 * (2 ** attempt)
                    print(f"    [网络] 请求异常: {e}，等待 {wait} 秒后重试...")
                    time.sleep(wait)
                else:
                    raise
        raise RateLimitError(f"请求失败: 连续 {MAX_RETRIES} 次均触发限频 (code: 103/3001008)")

    def _generate_sign(self, business_params=None):
        timestamp = self._get_timestamp()
        access_token = self._ensure_valid_token()
        params = {
            'access_token': access_token,
            'app_key': self.app_id,
            'timestamp': str(timestamp)
        }
        if business_params:
            params.update(business_params)

        sorted_params = sorted(params.items(), key=lambda x: x[0])
        param_parts = []
        for k, v in sorted_params:
            if v is None or v == "":
                continue
            if isinstance(v, (list, dict)):
                v = json.dumps(v, separators=(',', ':'))
            param_parts.append(f"{k}={v}")
        param_str = "&".join(param_parts)

        md5_hash = hashlib.md5(param_str.encode('utf-8')).hexdigest().upper()

        key = self.app_id.encode('utf-8')
        if len(key) < 16:
            key = key.ljust(16, b'\0')
        else:
            key = key[:16]

        cipher = AES.new(key, AES.MODE_ECB)
        pad_length = 16 - (len(md5_hash) % 16)
        padded_data = md5_hash.encode('utf-8') + bytes([pad_length]) * pad_length
        aes_encrypted = cipher.encrypt(padded_data)
        sign_base64 = base64.b64encode(aes_encrypted).decode('utf-8')
        sign_encoded = quote(sign_base64, safe='')

        return sign_encoded, timestamp

    def _build_request_params(self, business_params=None):
        sign, timestamp = self._generate_sign(business_params)
        return {
            'access_token': self.access_token,
            'app_key': self.app_id,
            'timestamp': timestamp,
            'sign': sign
        }

    def get(self, path, body=None):
        url = f"{self.base_domain}{path}"
        query_params = self._build_request_params(body)
        result = self._request_with_retry("GET", url, params=query_params, timeout=30)
        return result.get('data')

    def post(self, path, body=None):
        url = f"{self.base_domain}{path}"
        query_params = self._build_request_params(body)
        headers = {'Content-Type': 'application/json', 'X-API-VERSION': '2'}
        result = self._request_with_retry(
            "POST", url, params=query_params, json=body or {},
            headers=headers, timeout=20
        )
        return result.get('data')
