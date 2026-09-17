"""Optional NAVER API HUB image enrichment, isolated from recommendations."""
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
import hashlib, json, os, re, sqlite3
import tempfile
from threading import Lock
from time import time
from typing import Any
import requests
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / "core" / ".env")

IMAGE_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/image"
MAX_BATCH_SIZE = 6
DEFAULT_CACHE_ROOT = Path(tempfile.gettempdir()) / "KOALA" / "cache"
CACHE_PATH = Path(os.getenv("KOALA_CACHE_DIR", DEFAULT_CACHE_ROOT)) / "place_images.sqlite3"
IMAGE_CACHE_DIR = CACHE_PATH.parent / "images"
_cache_lock = Lock()

def naver_credentials():
    client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
    secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    return (client_id, secret) if client_id and secret else None

def _plain(value): return re.sub(r"<[^>]+>", "", unescape(value or "")).strip()
def _normalized(value): return re.sub(r"[^0-9a-z가-힣]", "", _plain(value).casefold())
def _key(name, address): return hashlib.sha256(f"{_normalized(name)}|{_normalized(address)}".encode()).hexdigest()

def _connect():
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(CACHE_PATH, timeout=3)
    db.execute("CREATE TABLE IF NOT EXISTS place_image_cache (cache_key TEXT PRIMARY KEY, place_name TEXT NOT NULL, address TEXT, payload TEXT, expires_at INTEGER NOT NULL)")
    return db

def _cache_get(key):
    with _cache_lock, _connect() as db:
        row = db.execute("SELECT payload, expires_at FROM place_image_cache WHERE cache_key=?", (key,)).fetchone()
        if not row or row[1] <= int(time()):
            if row: db.execute("DELETE FROM place_image_cache WHERE cache_key=?", (key,))
            return False
        return json.loads(row[0]) if row[0] else None

def _cache_put(key, name, address, payload):
    ttl = 7 * 86400 if payload else 3600
    with _cache_lock, _connect() as db:
        db.execute("INSERT OR REPLACE INTO place_image_cache VALUES (?,?,?,?,?)", (key, name, address, json.dumps(payload, ensure_ascii=False) if payload else None, int(time()) + ttl))

def _download_image(key: str, remote_url: str):
    response = requests.get(
        remote_url,
        headers={"User-Agent": "KOALA/1.0", "Referer": "https://search.naver.com/"},
        timeout=6,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    if not content_type.startswith("image/") or not response.content or len(response.content) > 5_000_000:
        return None
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGE_CACHE_DIR / f"{key}.bin").write_bytes(response.content)
    (IMAGE_CACHE_DIR / f"{key}.type").write_text(content_type, encoding="ascii")
    return f"/place-media/image/{key}"

def get_cached_image(key: str):
    if not re.fullmatch(r"[0-9a-f]{64}", key): return None
    image_path, type_path = IMAGE_CACHE_DIR / f"{key}.bin", IMAGE_CACHE_DIR / f"{key}.type"
    if not image_path.is_file() or not type_path.is_file(): return None
    return image_path.read_bytes(), type_path.read_text(encoding="ascii").strip()

def _select_image(place_name: str, items: list[dict[str, Any]]):
    target, ranked = _normalized(place_name), []
    for index, item in enumerate(items):
        url = item.get("thumbnail") or item.get("link")
        if not url or not str(url).startswith("https://"): continue
        title = _plain(item.get("title")); title_key = _normalized(title)
        match = bool(target and (target in title_key or title_key in target))
        try: size = min(int(item.get("sizewidth", 0)), int(item.get("sizeheight", 0)))
        except (TypeError, ValueError): size = 0
        ranked.append((match, size, -index, item, title))
    if not ranked: return None
    _, _, _, chosen, title = max(ranked, key=lambda value: value[:3])
    return {"image_url": chosen.get("thumbnail") or chosen.get("link"), "thumbnail": chosen.get("thumbnail"), "original_image_url": chosen.get("link"), "title": title, "sizewidth": chosen.get("sizewidth"), "sizeheight": chosen.get("sizeheight"), "image_source": "naver_image_search", "image_attribution": "NAVER 이미지 검색", "image_attribution_url": chosen.get("link")}

def get_place_image(place_name: str, address: str = ""):
    credentials = naver_credentials()
    if not credentials or not place_name.strip(): return None
    key = _key(place_name, address); cached = _cache_get(key)
    if cached is not False:
        if cached and get_cached_image(key):
            cached["image_url"] = f"/place-media/image/{key}"
            return cached
        if cached is None: return None
    client_id, secret = credentials
    response = requests.get(IMAGE_SEARCH_URL, headers={"X-NCP-APIGW-API-KEY-ID": client_id, "X-NCP-APIGW-API-KEY": secret}, params={"query": f"{place_name} {address}".strip(), "display": 5, "sort": "sim", "filter": "large"}, timeout=5)
    response.raise_for_status()
    result = _select_image(place_name, response.json().get("items", []))
    if result:
        local_url = _download_image(key, result["image_url"])
        if not local_url: result = None
        else: result["image_url"] = local_url
    _cache_put(key, place_name, address, result)
    return result

def lookup_place_photos(items):
    if not naver_credentials(): return {"enabled": False, "photos": []}
    eligible = [item for item in items[:MAX_BATCH_SIZE] if item.get("category") in {"food", "cafe", "culture", "walk"}]
    def lookup(item):
        try:
            result = get_place_image(str(item.get("name") or ""), str(item.get("address") or ""))
            return {"client_key": item.get("client_key"), **result} if result else None
        except (requests.RequestException, ValueError, OSError, sqlite3.Error): return None
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(eligible)))) as pool:
        return {"enabled": True, "photos": [photo for photo in pool.map(lookup, eligible) if photo]}
