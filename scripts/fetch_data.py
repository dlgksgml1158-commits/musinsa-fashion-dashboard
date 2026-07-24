"""Fetches only public, non-proprietary data and writes JSON snapshots into ../data.

Sources reused (public, already-computed): musinsa/29cm real-time ranking + search trend feeds,
synced from the author's own already-public GitHub Pages data endpoint.
Sources fetched fresh (public, no auth): weather (Naver Weather search widget), fashion news (Google News RSS).
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

UPSTREAM_BASE = "https://dlgksgml1158-commits.github.io/musinsa-dashboard/data"
PUBLIC_UPSTREAM_FILES = [
    "musinsa.json",
    "29cm.json",
    "musinsa_search_trends.json",
    "naver_trends.json",
]

HEADERS = {"User-Agent": "musinsa-fashion-dashboard-bot"}
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def fetch_json(url, headers=None):
    return json.loads(fetch(url, headers))


def fetch_text(url, headers=None):
    return fetch(url, headers).decode("utf-8", errors="replace")


def sync_public_upstream_files():
    for name in PUBLIC_UPSTREAM_FILES:
        try:
            data = fetch_json(f"{UPSTREAM_BASE}/{name}?t={int(time.time() * 1000)}")
            # brandPriceStats holds the seller's own brand pricing stats (proprietary) — never publish it
            data.pop("brandPriceStats", None)
            (DATA_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))
            print(f"synced {name}")
        except Exception as e:
            print(f"failed {name}: {e}")


def _parse_naver_date(md_text, today):
    # md_text like "7.24." -> nearest matching date on/after `today`
    month, day = (int(x) for x in md_text.strip(".").split("."))
    year = today.year
    candidate = datetime(year, month, day).date()
    if candidate < today - timedelta(days=180):
        candidate = datetime(year + 1, month, day).date()
    return candidate.isoformat()


def fetch_weather():
    html = fetch_text("https://search.naver.com/search.naver?query=%EC%84%9C%EC%9A%B8%EB%82%A0%EC%94%A8")
    soup = BeautifulSoup(html, "html.parser")
    today = datetime.now(timezone.utc).astimezone().date()

    cur_temp_el = soup.select_one(".temperature_text")
    cur_temp = None
    if cur_temp_el:
        m = re.search(r"-?\d+(\.\d+)?", cur_temp_el.get_text())
        cur_temp = float(m.group()) if m else None
    cur_label_el = soup.select_one(".weather_main .blind")
    cur_label = cur_label_el.get_text(strip=True) if cur_label_el else "-"
    cur_detail_el = soup.select_one(".temperature_wrap .summary_list") or soup.select_one(".summary_list")
    feels_like = humidity = wind_speed = None
    if cur_detail_el:
        detail_text = cur_detail_el.get_text(" ", strip=True)
        m = re.search(r"체감\s*(-?\d+(\.\d+)?)", detail_text)
        feels_like = float(m.group(1)) if m else None
        m = re.search(r"습도\s*(\d+)", detail_text)
        humidity = int(m.group(1)) if m else None
        m = re.search(r"(\d+(\.\d+)?)\s*m/s", detail_text)
        wind_speed = float(m.group(1)) if m else None

    days = []
    for item in soup.select(".list_box._weekly_weather .week_item")[:7]:
        day_label = item.select_one(".day")
        date_el = item.select_one(".date")
        lowest_el = item.select_one(".lowest")
        highest_el = item.select_one(".highest")
        weather_blocks = item.select(".cell_weather .weather_inner")
        pm_block = weather_blocks[-1] if weather_blocks else None
        pm_icon_label = pm_block.select_one("i.wt_icon .blind") if pm_block else None
        pm_rain_el = pm_block.select_one(".rainfall") if pm_block else None

        if not (date_el and lowest_el and highest_el):
            continue
        t_min = float(re.search(r"-?\d+", lowest_el.get_text()).group())
        t_max = float(re.search(r"-?\d+", highest_el.get_text()).group())
        precip_prob = int(re.search(r"\d+", pm_rain_el.get_text()).group()) if pm_rain_el else 0
        days.append({
            "date": _parse_naver_date(date_el.get_text(), today),
            "dayLabel": day_label.get_text(strip=True) if day_label else "",
            "tMax": t_max,
            "tMin": t_min,
            "precipProb": precip_prob,
            "weatherLabel": pm_icon_label.get_text(strip=True) if pm_icon_label else "-",
        })

    if not days:
        raise RuntimeError("failed to parse Naver weekly weather forecast")

    avg_max = round(sum(d["tMax"] for d in days) / len(days))
    avg_min = round(sum(d["tMin"] for d in days) / len(days))
    rain_days = sum(1 for d in days if d["precipProb"] >= 40)

    return {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "네이버 날씨",
        "city": "서울",
        "current": {
            "temp": cur_temp,
            "weatherLabel": cur_label,
            "feelsLike": feels_like,
            "humidity": humidity,
            "windSpeed": wind_speed,
        },
        "week": {
            "avgMax": avg_max,
            "avgMin": avg_min,
            "rainDays": rain_days,
            "summary": f"{days[0]['date']} ~ {days[-1]['date']} 서울 주간 날씨: 평균 최고 {avg_max}°C, 최저 {avg_min}°C. 비 오는 날 {rain_days}일 포함.",
        },
        "days": days,
    }


# Verified against musinsa.com's live category tree (category/Category query under
# parents 001/002/003) — the seller's old dashboard used a stale code set that Musinsa
# has since renumbered (e.g. old "003002"="슬랙스" now resolves to "데님 팬츠").
MUSINSA_CATEGORY_LABELS = {
    "001001": "반소매 티셔츠",
    "001010": "긴소매 티셔츠",
    "001005": "맨투맨/스웨트",
    "001004": "후드 티셔츠",
    "001002": "셔츠/블라우스",
    "001006": "니트/스웨터",
    "002": "아우터",
    "003002": "데님 팬츠",
    "003008": "슬랙스",
    "003004": "트레이닝/조거",
    "003009": "반바지",
}


def _price_stats(items):
    prices = [i["finalPrice"] for i in items if i.get("finalPrice")]
    if not prices:
        return None
    return {
        "avg": round(sum(prices) / len(prices)),
        "min": min(prices),
        "max": max(prices),
        "count": len(prices),
    }


def fetch_musinsa_category_goods(code):
    # gf= in the URL is ignored by the server-rendered payload (always returns the
    # unfiltered popular list) — each item carries its own displayGenderText instead,
    # so gender split happens by grouping that field client-side (below).
    url = f"https://www.musinsa.com/category/{code}/goods?gf=A"
    html = fetch_text(url, headers=BROWSER_HEADERS)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError(f"no __NEXT_DATA__ for category {code}")
    data = json.loads(m.group(1))
    queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    target = next(q for q in queries if isinstance(q.get("queryKey"), list) and q["queryKey"][0] == code)
    return target["state"]["data"]["pages"][0]["data"]["list"]


def _normalize_item(raw, rank, code, label):
    return {
        "rank": rank,
        "id": f"ms-{raw.get('goodsNo')}",
        "brand": raw.get("brandName") or raw.get("brand") or "",
        "name": raw.get("goodsName", ""),
        "price": raw.get("normalPrice"),
        "originalPrice": raw.get("normalPrice"),
        "discountRate": raw.get("finalDiscount") or 0,
        "finalPrice": raw.get("finalPrice"),
        "category": code,
        "categoryLabel": label,
        "imgUrl": raw.get("thumbnail", ""),
        "productUrl": raw.get("goodsLinkUrl", ""),
        "displayGenderText": raw.get("displayGenderText", ""),
    }


def fetch_category_price_by_gender():
    categories = {}
    for code, label in MUSINSA_CATEGORY_LABELS.items():
        try:
            items = fetch_musinsa_category_goods(code)
        except Exception as e:
            print(f"failed musinsa category {code}: {e}")
            continue
        normalized = [_normalize_item(it, i + 1, code, label) for i, it in enumerate(items)]
        categories[code] = {
            "label": label,
            "all": _price_stats(items),
            "male": _price_stats([i for i in items if i.get("displayGenderText") == "남성"]),
            "female": _price_stats([i for i in items if i.get("displayGenderText") == "여성"]),
            "items": normalized[:20],
        }
        time.sleep(0.5)
    return {"updatedAt": datetime.now(timezone.utc).isoformat(), "categories": categories}


ENTITY_MAP = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}


def decode_entities(s):
    for k, v in ENTITY_MAP.items():
        s = s.replace(k, v)
    return s


def fetch_fashion_news():
    url = "https://news.google.com/rss/search?q=%ED%8C%A8%EC%85%98%20%EB%B8%8C%EB%9E%9C%EB%93%9C&hl=ko&gl=KR&ceid=KR:ko"
    xml = fetch_text(url)
    items = []
    for block in re.findall(r"<item>([\s\S]*?)</item>", xml)[:10]:
        title_m = re.search(r"<title>([\s\S]*?)</title>", block)
        link_m = re.search(r"<link>([\s\S]*?)</link>", block)
        pub_m = re.search(r"<pubDate>([\s\S]*?)</pubDate>", block)
        src_m = re.search(r"<source[^>]*>([\s\S]*?)</source>", block)
        items.append({
            "title": decode_entities(title_m.group(1)) if title_m else "",
            "link": link_m.group(1) if link_m else "",
            "pubDate": pub_m.group(1) if pub_m else "",
            "source": decode_entities(src_m.group(1)) if src_m else "",
        })
    return {"updatedAt": datetime.now(timezone.utc).isoformat(), "items": items}


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sync_public_upstream_files()

    try:
        weather = fetch_weather()
        (DATA_DIR / "weather.json").write_text(json.dumps(weather, ensure_ascii=False, indent=2))
        print("synced weather.json")
    except Exception as e:
        print(f"failed weather.json: {e}")

    try:
        news = fetch_fashion_news()
        (DATA_DIR / "fashion_news.json").write_text(json.dumps(news, ensure_ascii=False, indent=2))
        print("synced fashion_news.json")
    except Exception as e:
        print(f"failed fashion_news.json: {e}")

    try:
        gender_price = fetch_category_price_by_gender()
        (DATA_DIR / "musinsa_category_price_by_gender.json").write_text(
            json.dumps(gender_price, ensure_ascii=False, indent=2)
        )
        print("synced musinsa_category_price_by_gender.json")
    except Exception as e:
        print(f"failed musinsa_category_price_by_gender.json: {e}")

    (DATA_DIR / "meta.json").write_text(
        json.dumps({"updatedAt": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
