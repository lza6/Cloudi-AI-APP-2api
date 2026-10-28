#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudi AI v1.0.9 (com.cloudi.ai.image.video.generator) → OpenAI 兼容 2API demo server
逆向成果: 静态(jadx+capstone so 分析) + Firebase Remote Config 密钥下发 + 实测验证

鉴权链:
  X-Client-Auth = base64(AES-256-CBC(plaintext, aes_key, aes_iv))
  plaintext     = "{unix_now}||com.cloudi.ai.image.video.generator||{unix_now+60}"
  aes_key/iv    = Firebase Remote Config 下发 (aes_key/aes_iv)
上游: https://nano-banana.leansoft-ai.com (Cloudflare Worker)

已实测端点:
  /user/deviceId      注册设备 → SaasID            ✅ 200
  /activeUser         每日配额 (usesLeft/coins)     ✅ 200
  /action/rewarded    广告奖励 +50 coins            ✅ 200
  /genUploadLink      生成 Wasabi 预签上传链        ✅ 200
  /upload/image-v3    multipart 直传图床            ✅ 200
  /image/enhance      图片增强                      ✅ 200 success
  /image/prompt       文生图(需 tokenData 会话)     ⚠️ Quota limit 墙
  /image/img2img/v2   风格化图生图                  ⚠️ style 校验未通
  /video/createTask   文生视频                      ❌ 上游 DOMAIN_SUSPENDED

用法: python demo_server.py [port]   默认 8902
"""
import base64
import hashlib
import json
import os
import random
import struct
import sys
import time
import urllib.request
import urllib.error
import uuid

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad

# ============ 逆向还原的常量 ============
PKG = "com.cloudi.ai.image.video.generator"
BASE_URL = os.environ.get("CLOUDI_BASE_URL", "https://nano-banana.leansoft-ai.com")
APP_VERSION = "1.0.9"
VERSION_CODE = "9"

# Firebase Remote Config (可被服务端随时轮换 — demo 启动时动态拉取)
FIREBASE_API_KEY = "AIzaSyDNLO-whFs8FEU7iBf7morGygMLIzqpNvs"
FIREBASE_PROJECT = "ls62---ai-video-2"
FIREBASE_APP_ID = "1:361631943274:android:3b316bdb89462a56001813"


def fetch_remote_config():
    """从 Firebase Installations + Remote Config 拉取动态配置 (baseUrl/aes_key/aes_iv)"""
    try:
        body = json.dumps({
            "fid": uuid.uuid4().hex, "appId": FIREBASE_APP_ID,
            "authVersion": "FIS_v2", "sdkVersion": "a:23.1.0",
        }).encode()
        req = urllib.request.Request(
            f"https://firebaseinstallations.googleapis.com/v1/projects/{FIREBASE_PROJECT}/installations?key={FIREBASE_API_KEY}",
            data=body, headers={"Content-Type": "application/json"})
        fis = json.loads(urllib.request.urlopen(req, timeout=15).read())
        fid = fis["fid"]
        req = urllib.request.Request(
            f"https://firebaseremoteconfig.googleapis.com/v1/projects/{FIREBASE_PROJECT}/namespaces/firebase:fetch",
            data=json.dumps({"app_id": FIREBASE_APP_ID, "app_instance_id": fid,
                             "sdk_version": "Android-23.1.0"}).encode(),
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": FIREBASE_API_KEY,
                     "X-Firebase-AppInstance-Id": fid})
        rc = json.loads(urllib.request.urlopen(req, timeout=15).read())
        e = rc.get("entries", {})
        return {"base_url": e.get("base_url", BASE_URL), "aes_key": e.get("aes_key"),
                "aes_iv": e.get("aes_iv")}
    except Exception as ex:
        print(f"[warn] remote config fetch failed: {ex}, using baked-in values")
        return {"base_url": BASE_URL, "aes_key": "nV2t6sQ8JzWyXCMkURa4BEfDq1oZLgMb",
                "aes_iv": "W9pYdK3eRuBvMzQ2"}


RC = fetch_remote_config()
AES_KEY = (RC["aes_key"] or "").encode()
AES_IV = (RC["aes_iv"] or "").encode()
BASE_URL = RC["base_url"]


def make_client_token() -> str:
    """还原 libnativelib.so encryptString: AES-256-CBC('now||pkg||now+60') + base64"""
    now = int(time.time())
    pt = f"{now}||{PKG}||{now + 60}".encode()
    return base64.b64encode(AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(pt, 16))).decode()


def make_headers(device_id: str, app_user_id: str = "") -> dict:
    return {
        "Content-Type": "application/json",
        "X-Client-Auth": make_client_token(),
        "device-id": device_id,
        "app-user-id": app_user_id,
        "app-version": APP_VERSION,
        "version-code": VERSION_CODE,
        "language-code": "en",
        "app-id": PKG,
        "os-type": "android",
        "User-Agent": "okhttp/4.12.0",
    }


class CloudiSession:
    """一个设备会话: 注册 → 配额 → 上传 → 生成"""

    def __init__(self):
        self.android_id = "".join(random.choices("0123456789abcdef", k=16))
        self.saas_id = None

    def _post(self, path: str, body=None, timeout=60):
        dev = self.saas_id or self.android_id
        req = urllib.request.Request(
            BASE_URL + path,
            data=(json.dumps(body or {}).encode() if body is not None else b"{}"),
            headers=make_headers(dev, self.saas_id or ""))
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

    def bootstrap(self):
        """设备注册 + 每日配额激活"""
        r = self._post("/user/deviceId", {
            "ad_id": "", "country_code": "US", "language_code": "en",
            "device_model": "Pixel 8", "android_id": self.android_id, "android_sdk": "34"})
        self.saas_id = r["data"]["deviceId"]
        quota = self._post("/activeUser")
        return {"android_id": self.android_id, "saas_id": self.saas_id,
                "quota": quota.get("data", {}).get("dailyQuota")}

    def rewarded(self):
        """广告奖励 (coins +50)"""
        return self._post("/action/rewarded")

    def upload_jpeg(self, jpeg: bytes) -> str:
        """genUploadLink → POST 预签 URL → 返回 image_name"""
        r = self._post("/genUploadLink", {"fileName": "img.jpg", "mimeType": "image/jpeg"})
        req = urllib.request.Request(r["uploadUrl"], data=jpeg, method="POST")
        req.add_header("Content-Type", "image/jpeg")
        req.add_header("User-Agent", "okhttp/4.12.0")
        urllib.request.urlopen(req, timeout=30)
        return r["filename"]

    def upload_multipart_v3(self, jpeg: bytes) -> str:
        """/upload/image-v3 multipart 直传"""
        boundary = "----" + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="img.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode()
        body += jpeg + f"\r\n--{boundary}--\r\n".encode()
        h = make_headers(self.saas_id or self.android_id, self.saas_id or "")
        h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(BASE_URL + "/upload/image-v3", data=body, headers=h)
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return r["data"]["imageUrl"]

    def enhance(self, image_name: str):
        return self._post("/image/enhance", {"image_name": image_name}, timeout=120)

    def generate_prompt(self, image_name: str, prompt: str):
        """文生图(基于底图) — 受上游配额墙限制"""
        return self._post("/image/prompt", {"image_name": image_name, "prompt": prompt}, timeout=180)

    def img2img(self, image_name: str, style_id: str, **kw):
        body = {"image_name": image_name, "style_id": style_id, "strength": 60,
                "width": 1024, "height": 1024, "url": f"https://cdn.leansoft-ai.com/{image_name}",
                "deviceNum": "", "deviceId": self.saas_id or self.android_id, "countryCode": "US"}
        body.update(kw)
        return self._post("/image/img2img/v2", body, timeout=180)

    def video_create_task(self, jpeg: bytes, prompt: str, video_prompt: str = "video_motion"):
        boundary = "----" + uuid.uuid4().hex
        fields = {"prompt": prompt, "video_prompt": video_prompt,
                  "model_type": "v_fuse", "aspect_ratio": "16:9"}
        body = b""
        for k, v in fields.items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                 f'filename="img.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode() + jpeg
        body += f"\r\n--{boundary}--\r\n".encode()
        h = make_headers(self.saas_id or self.android_id, self.saas_id or "")
        h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(BASE_URL + "/video/createTask", data=body, headers=h)
        try:
            return json.loads(urllib.request.urlopen(req, timeout=120).read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())


# ============ OpenAI 兼容层 ============
MIN_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


def oai_error(msg, code=502):
    return {"error": {"message": msg, "type": "upstream_error", "code": code}}


def handle_chat_completions(payload: dict):
    """OpenAI /v1/chat/completions → Cloudi 图片增强/文生图链路 (demo: 文本回答走 quota 报告)"""
    prompt = ""
    for m in payload.get("messages", []):
        prompt += m.get("content", "") + "\n"
    prompt = prompt.strip()
    sess = CloudiSession()
    boot = sess.bootstrap()
    try:
        img_name = sess.upload_jpeg(MIN_JPEG)
        r = sess.generate_prompt(img_name, prompt[:500])
        if r.get("success"):
            return {"id": "chatcmpl-" + uuid.uuid4().hex[:12], "object": "chat.completion",
                    "created": int(time.time()), "model": payload.get("model", "cloudi-nano-banana"),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(r)},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        return r, 502
    except Exception as ex:
        return oai_error(str(ex))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8902
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _send(self, obj, code=200, ctype="application/json"):
            data = json.dumps(obj, ensure_ascii=False).encode() if not isinstance(obj, bytes) else obj
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/health"):
                self._send({"service": "cloudi-2api", "upstream": BASE_URL,
                            "aes_key_prefix": AES_KEY[:4].decode(errors="replace"),
                            "status": "ok"})
            elif self.path == "/v1/models":
                self._send({"object": "list", "data": [
                    {"id": "cloudi-nano-banana", "object": "model"},
                    {"id": "cloudi-enhance", "object": "model"},
                    {"id": "cloudi-video", "object": "model"}]})
            elif self.path == "/v1/session" or self.path == "/v1/session/bootstrap":
                self._send(CloudiSession().bootstrap())
            else:
                self._send(oai_error("not found", 404), 404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n)
            try:
                if self.path == "/v1/chat/completions":
                    out = handle_chat_completions(json.loads(raw))
                    if isinstance(out, tuple):
                        self._send(out[0], out[1])
                    else:
                        self._send(out)
                elif self.path == "/v1/session/bootstrap":
                    self._send(CloudiSession().bootstrap())
                elif self.path == "/v1/session/rewarded":
                    s = CloudiSession(); s.bootstrap()
                    self._send(s.rewarded())
                elif self.path == "/v1/image/enhance":
                    p = json.loads(raw)
                    jpeg = base64.b64decode(p["image_b64"]) if "image_b64" in p else MIN_JPEG
                    s = CloudiSession(); s.bootstrap()
                    name = s.upload_jpeg(jpeg)
                    self._send(s.enhance(name))
                elif self.path == "/v1/image/generate":
                    p = json.loads(raw)
                    s = CloudiSession(); s.bootstrap()
                    name = s.upload_jpeg(MIN_JPEG)
                    self._send(s.generate_prompt(name, p.get("prompt", "")))
                else:
                    self._send(oai_error("not found", 404), 404)
            except Exception as ex:
                self._send(oai_error(str(ex)))

        def log_message(self, fmt, *args):
            print(f"[{time.strftime('%H:%M:%S')}] {self.command} {self.path}")

    print(f"Cloudi AI 2API demo server")
    print(f"  upstream : {BASE_URL}")
    print(f"  aes_key  : {AES_KEY.decode()} ({len(AES_KEY)}B)  aes_iv: {AES_IV.decode()}")
    print(f"  listen   : http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
