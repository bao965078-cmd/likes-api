import asyncio
import binascii
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import gzip
import http.client
from io import BytesIO
import json
import os
import ssl
import threading
import time
import warnings
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad as aes_pad
import aiohttp
from flask import Flask, jsonify, request
from google.protobuf.json_format import MessageToJson
import requests
from urllib3.exceptions import InsecureRequestWarning
import like_count_pb2
import like_pb2
import my_pb2
import output_pb2
import uid_generator_pb2

app = Flask(__name__)
warnings.filterwarnings("ignore", category=InsecureRequestWarning)

TOKEN_FILE = "token_bd.json"
ACC_FILE = "acc.txt"
AES_KEY = b"Yg&tc%DEuh6%Zc^8"
AES_IV = b"6oyZDr22E3ychjM%"
TOKEN_REFRESH_INTERVAL = 8 * 60 * 60
LOGIN_RETRY = 2
TOKEN_POOL = {}
REGION = "BD"
_executor = ThreadPoolExecutor(max_workers=100)
CHECK_REGIONS = ["IND", "BR", "BD", "SG", "MY", "TH", "VN", "ID", "PK", "RU", "ME", "EG"]

def aes_encrypt_raw(plaintext):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(aes_pad(plaintext, AES.block_size))

def encrypt_message(plaintext):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return binascii.hexlify(cipher.encrypt(aes_pad(plaintext, AES.block_size))).decode()

def enc(uid):
    msg = uid_generator_pb2.uid_generator()
    msg.saturn_ = int(uid)
    msg.garena = 1
    return encrypt_message(msg.SerializeToString())

def get_oauth_token(uid, password, retries=5):
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    headers = {
        "Host": "100067.connect.garena.com",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 7.1.2; ASUS_Z01QD Build/QKQ1.190825.002)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "close",
    }
    payload = {
        "uid": uid,
        "password": password,
        "response_type": "token",
        "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067",
    }
    for attempt in range(1, retries + 1):
        try:
            if attempt > 1:
                time.sleep(min(5 * attempt, 30))
            r = requests.post(url, headers=headers, data=payload, timeout=8)
            if r.status_code == 429:
                print(f"⚠️ UID {uid} - Rate limit, chờ 10s (lần {attempt}/{retries})")
                time.sleep(10)
                continue
            if r.status_code == 200:
                j = r.json()
                open_id = j.get("open_id")
                access_token = j.get("access_token")
                if open_id and access_token:
                    return {"access_token": access_token, "open_id": open_id}
                token = j.get("token") or j.get("session_key") or j.get("jwt") or (j.get("data") or {}).get("token")
                if token:
                    return {"access_token": token, "open_id": open_id or ""}
            else:
                print(f"⚠️ UID {uid} - HTTP {r.status_code} (lần {attempt}/{retries})")
        except Exception as e:
            print(f"⚠️ UID {uid} - Lỗi: {e} (lần {attempt}/{retries})")
    return {"error": f"OAuth failed after {retries} attempts"}

def major_login_http(encrypted_bytes):
    context = ssl._create_unverified_context()
    conn = http.client.HTTPSConnection("loginbp.ggpolarbear.com", context=context, timeout=10)
    hr = {
        "X-Unity-Version": "2018.4.11f1",
        "ReleaseVersion": "OB54",
        "Content-Type": "application/octet-stream",
        "X-GA": "v1 1",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 7.1.2; ASUS_Z01QD Build/QKQ1.190825.002)",
        "Host": "loginbp.ggpolarbear.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Expect": "100-continue",
    }
    try:
        conn.request("POST", "/MajorLogin", body=encrypted_bytes, headers=hr)
        resp = conn.getresponse()
        raw = resp.read()
        if resp.getheader("Content-Encoding") == "gzip":
            with gzip.GzipFile(fileobj=BytesIO(raw)) as f:
                raw = f.read()
        if resp.status in (200, 201):
            return raw
        print(f"⚠️ MajorLogin HTTP {resp.status}")
        return None
    except Exception as e:
        print(f"⚠️ MajorLogin Error: {e}")
        return None
    finally:
        conn.close()

def parse_login_response(response_bytes):
    try:
        msg = output_pb2.Garena_420()
        msg.ParseFromString(response_bytes)
        result = {}
        for line in str(msg).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip().strip('"')
        return result
    except:
        return {"error": "parse error"}

def login_account(uid, password):
    last_error = "Unknown"
    for attempt in range(1, LOGIN_RETRY + 1):
        oauth = get_oauth_token(uid, password)
        if "error" in oauth or not oauth.get("access_token"):
            last_error = oauth.get("error", "No access_token")
            print(f"❌ UID {uid} - OAuth thất bại: {last_error}")
            if attempt < LOGIN_RETRY:
                time.sleep(attempt)
            continue
        access_token = oauth["access_token"]
        open_id = oauth.get("open_id", "")
        gd = my_pb2.GameData()
        gd.timestamp = "2024-12-05 18:15:32"
        gd.game_name = "free fire"
        gd.game_version = 2
        gd.version_code = "1.126.2"
        gd.os_info = "Android OS 9 / API-28 (PI/rel.cjw.20220518.114133)"
        gd.device_type = "Handheld"
        gd.network_provider = "Verizon Wireless"
        gd.connection_type = "WIFI"
        gd.screen_width = 1280
        gd.screen_height = 960
        gd.dpi = "240"
        gd.cpu_info = "ARMv7 VFPv3 NEON VMH | 2400 | 4"
        gd.total_ram = 5951
        gd.gpu_name = "Adreno (TM) 640"
        gd.gpu_version = "OpenGL ES 3.0"
        gd.user_id = "Google|74b585a9-0268-4ad3-8f36-ef41d2e53610"
        gd.ip_address = "172.190.111.97"
        gd.language = "en"
        gd.open_id = open_id
        gd.access_token = access_token
        gd.platform_type = 4
        gd.device_form_factor = "Handheld"
        gd.device_model = "Asus ASUS_I005DA"
        gd.field_60 = 32968
        gd.field_61 = 29815
        gd.field_62 = 2479
        gd.field_63 = 914
        gd.field_64 = 31213
        gd.field_65 = 32968
        gd.field_66 = 31213
        gd.field_67 = 32968
        gd.field_70 = 4
        gd.field_73 = 2
        gd.library_path = "/data/app/com.dts.freefireth-QPvBnTUhYWE-7DMZSOGdmA==/lib/arm"
        gd.field_76 = 1
        gd.apk_info = "5b892aaabd688e571f688053118a162b|/data/app/com.dts.freefireth-QPvBnTUhYWE-7DMZSOGdmA==/base.apk"
        gd.field_78 = 6
        gd.field_79 = 1
        gd.os_architecture = "32"
        gd.build_number = "2019120270"
        gd.field_85 = 1
        gd.graphics_backend = "OpenGLES2"
        gd.max_texture_units = 16383
        gd.rendering_api = 4
        gd.encoded_field_89 = "\u0017T\u0011\u0017\u0002\b\u000eUMQ\bEZ\u0003@ZK;Z\u0002\u000eV\ri[QVi\u0003\ro\t\u0007e"
        gd.field_92 = 9204
        gd.marketplace = "3rd_party"
        gd.encryption_key = "KqsHT2B4It60T/65PGR5PXwFxQkVjGNi+IMCK3CFBCBfrNpSUA1dZnjaT3HcYchlIFFL1ZJOg0cnulKCPGD3C3h1eFQ="
        gd.total_storage = 111107
        gd.field_97 = 1
        gd.field_98 = 1
        gd.field_99 = "4"
        gd.field_100 = "4"
        encrypted = aes_encrypt_raw(gd.SerializeToString())
        raw = major_login_http(encrypted)
        if not raw:
            last_error = "MajorLogin no response"
            print(f"❌ UID {uid} - MajorLogin không phản hồi")
            if attempt < LOGIN_RETRY:
                time.sleep(attempt)
            continue
        parsed = parse_login_response(raw)
        jwt = parsed.get("token", "")
        if not jwt or jwt in ("", "N/A", "null"):
            last_error = "No JWT in response"
            print(f"❌ UID {uid} - Không có JWT trong response")
            if attempt < LOGIN_RETRY:
                time.sleep(attempt)
            continue
        print(f"✅ UID {uid} - Lấy token thành công")
        return {"success": True, "uid": str(uid), "token": jwt}
    print(f"❌ UID {uid} - Thất bại sau {LOGIN_RETRY} lần thử: {last_error}")
    return {"success": False, "error": last_error, "uid": uid}

def load_accounts():
    if not os.path.exists(ACC_FILE):
        print(f"⚠️ Không tìm thấy {ACC_FILE}")
        return []
    accounts = []
    with open(ACC_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            uid, password = line.split(":", 1)
            accounts.append({"uid": uid.strip(), "password": password.strip()})
    print(f"📂 Loaded {len(accounts)} accounts từ {ACC_FILE}")
    return accounts

def _save_token_file(token_list):
    payload = {"created_at": time.time(), "tokens": token_list}
    tmp = TOKEN_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, TOKEN_FILE)
    print(f"💾 Đã lưu {len(token_list)} tokens vào {TOKEN_FILE}")

def _load_token_file():
    if not os.path.exists(TOKEN_FILE):
        return 0.0, []
    with open(TOKEN_FILE, "r") as f:
        data = json.load(f)
    if isinstance(data, list):
        return 0.0, [t for t in data if t.get("token") not in ("", "N/A", None)]
    created_at = data.get("created_at", 0.0)
    tokens = [item for item in data.get("tokens", []) if item.get("token") not in ("", "N/A", None)]
    return created_at, tokens

def is_token_expired():
    created_at, tokens = _load_token_file()
    if not tokens:
        return True
    return (time.time() - created_at) >= TOKEN_REFRESH_INTERVAL

def refresh_all_tokens():
    accounts = load_accounts()
    if not accounts:
        print("⚠️ Không có account để refresh token")
        return
    total = len(accounts)
    print(f"🔄 Bắt đầu lấy JWT cho {total} accounts...")
    print("=" * 50)
    token_list = []
    success_count = 0
    failed_count = 0
    PER_ACCOUNT_TIMEOUT = 30
    futures = {_executor.submit(login_account, a["uid"], a["password"]): a for a in accounts}
    pending = set(futures.keys())
    i = 0
    deadline = time.time() + total * PER_ACCOUNT_TIMEOUT
    while pending:
        remaining_time = deadline - time.time()
        if remaining_time <= 0:
            for f in pending:
                acc = futures[f]
                failed_count += 1
                print(f"⏱️ UID {acc['uid']} - Timeout")
            break
        done, pending = wait(pending, timeout=min(PER_ACCOUNT_TIMEOUT, remaining_time), return_when=FIRST_COMPLETED)
        if not done:
            for f in pending:
                acc = futures[f]
                failed_count += 1
                print(f"⏱️ UID {acc['uid']} - Bị treo")
            break
        for future in done:
            i += 1
            acc = futures[future]
            try:
                result = future.result(timeout=1)
                if result.get("success"):
                    token_list.append({"uid": result["uid"], "token": result["token"]})
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                print(f"❌ UID {acc['uid']} - Exception: {e}")
    print("=" * 50)
    print(f"📊 Kết quả: ✅ {success_count} thành công | ❌ {failed_count} thất bại | Tổng: {total}")
    if token_list:
        _save_token_file(token_list)
        TOKEN_POOL[REGION] = {
            "all_tokens": [t["token"] for t in token_list],
            "current_index": 0,
            "total_tokens": len(token_list),
        }
    print("✅ Refresh hoàn tất!")

def ensure_tokens_valid():
    if is_token_expired():
        print("⏰ Token hết hạn hoặc chưa có, bắt đầu refresh...")
        refresh_all_tokens()
    else:
        _, token_list = _load_token_file()
        TOKEN_POOL[REGION] = {
            "all_tokens": [t["token"] for t in token_list],
            "current_index": 0,
            "total_tokens": len(token_list),
        }
        created_at, _ = _load_token_file()
        remaining = TOKEN_REFRESH_INTERVAL - (time.time() - created_at)
        print(f"✅ Token còn hạn ({int(remaining//60)} phút), loaded {len(token_list)} tokens")

def token_refresh_loop():
    while True:
        try:
            if is_token_expired():
                print("🔄 Background refresh tokens...")
                refresh_all_tokens()
            time.sleep(60)
        except Exception as e:
            print(f"❌ Lỗi refresh loop: {e}")
            time.sleep(60)

def load_tokens():
    pool = TOKEN_POOL.get(REGION, {})
    if pool.get("all_tokens"):
        return [{"token": t} for t in pool["all_tokens"]]
    _, token_list = _load_token_file()
    return token_list

def get_next_token():
    if REGION not in TOKEN_POOL or TOKEN_POOL[REGION].get("total_tokens", 0) == 0:
        ensure_tokens_valid()
    pool = TOKEN_POOL.get(REGION, {})
    total = pool.get("total_tokens", 0)
    if total == 0:
        return ""
    idx = pool["current_index"]
    token = pool["all_tokens"][idx]
    pool["current_index"] = (idx + 1) % total
    return token

async def send_request(session, edata, token, url, headers):
    try:
        async with session.post(url, data=edata, headers={**headers, "Authorization": f"Bearer {token}"}) as r:
            return await r.text()
    except:
        return None

async def send_multiple_requests(uid, server_name, url):
    msg = like_pb2.like()
    msg.uid = int(uid)
    msg.region = server_name
    encrypted = encrypt_message(msg.SerializeToString())
    edata = bytes.fromhex(encrypted)
    tokens = load_tokens()
    if not tokens:
        return []
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/x-www-form-urlencoded",
        "Expect": "100-continue",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB54",
    }
    async with aiohttp.ClientSession() as session:
        tasks = [send_request(session, edata, tokens[i % len(tokens)]["token"], url, headers) for i in range(200)]
        return await asyncio.gather(*tasks, return_exceptions=True)

def make_request(encrypt, server_name, token):
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow" if server_name == "IND" else ("https://client.us.freefiremobile.com/GetPlayerPersonalShow" if server_name in {"BR", "US", "SAC", "NA"} else "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow")
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Expect": "100-continue",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB54",
    }
    try:
        r = requests.post(url, data=bytes.fromhex(encrypt), headers=headers, verify=False)
        if r.status_code != 200:
            return None
        items = like_count_pb2.Info()
        items.ParseFromString(r.content)
        return items
    except:
        return None

def detect_region(uid, token):
    encrypted_uid = enc(uid)
    for region in CHECK_REGIONS:
        try:
            result = make_request(encrypted_uid, region, token)
            if result:
                data = json.loads(MessageToJson(result))
                account_info = data.get("AccountInfo", {})
                if account_info.get("UID", 0) == int(uid) or account_info.get("PlayerNickname"):
                    print(f"📍 UID {uid} thuộc region: {region}")
                    return region
        except:
            continue
    print(f"⚠️ Không xác định được region cho UID {uid}, mặc định BD")
    return "BD"

def get_region_url(region):
    if region == "IND":
        return "https://client.ind.freefiremobile.com"
    elif region in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com"
    else:
        return "https://clientbp.ggpolarbear.com"

@app.route("/like", methods=["GET"])
def handle_requests():
    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()
    if not uid:
        return jsonify({"error": "UID is required"}), 400
    try:
        token = get_next_token()
        if not token:
            return jsonify({"error": "No token available"}), 500
        if not region:
            region = detect_region(uid, token)
        encrypted_uid = enc(uid)
        start_time = time.time()
        before = make_request(encrypted_uid, region, token)
        if not before:
            return jsonify({"error": "Failed to retrieve player info"}), 500
        before_data = json.loads(MessageToJson(before))
        before_like = int(before_data.get("AccountInfo", {}).get("Likes", 0))
        user_info_before = before_data.get("AccountInfo", {})
        account_uid = user_info_before.get("UID", int(uid))
        account_name = user_info_before.get("PlayerNickname", "")
        account_region = user_info_before.get("Region", region)
        account_level = user_info_before.get("Level", 0)
        account_likes = before_like
        base_url = get_region_url(region)
        like_url = f"{base_url}/LikeProfile"
        asyncio.run(send_multiple_requests(uid, region, like_url))
        after = make_request(encrypted_uid, region, token)
        if not after:
            return jsonify({"error": "Failed to retrieve player info after likes"}), 500
        after_data = json.loads(MessageToJson(after))
        after_like = int(after_data.get("AccountInfo", {}).get("Likes", 0))
        like_given = after_like - before_like
        end_time = time.time()
        return jsonify({
            "result": {
                "User Info": {
                    "Account UID": account_uid,
                    "Account Name": account_name,
                    "Account Region": account_region,
                    "Account Level": account_level,
                    "Account Likes": account_likes
                },
                "Likes Info": {
                    "Likes Before": before_like,
                    "Likes After": after_like,
                    "Likes Added": like_given,
                    "Likes start of day": max(0, after_like - 100),
                },
                "API": {
                    "speeds": "{:.1f}s".format(end_time - start_time),
                    "Success": like_given > 0,
                }
            }
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/token-status", methods=["GET"])
def route_token_status():
    created_at, token_list = _load_token_file()
    elapsed = time.time() - created_at if created_at else 0
    remaining = max(0, TOKEN_REFRESH_INTERVAL - elapsed)
    return jsonify({
        "total_tokens": len(token_list),
        "expired": elapsed >= TOKEN_REFRESH_INTERVAL,
        "remaining_minutes": int(remaining // 60),
        "current_index": TOKEN_POOL.get(REGION, {}).get("current_index", 0),
    })

@app.route("/refresh-tokens", methods=["POST"])
def route_refresh_tokens():
    threading.Thread(target=refresh_all_tokens, daemon=True).start()
    return jsonify({"status": "refresh_started"}), 200

if __name__ == "__main__":
    print("🚀 Khởi động app...")
    ensure_tokens_valid()
    threading.Thread(target=token_refresh_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=3031, debug=False, use_reloader=False)