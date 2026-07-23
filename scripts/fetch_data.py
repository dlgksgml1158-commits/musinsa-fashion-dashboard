"""Fetches only public, non-proprietary data and writes JSON snapshots into ../data.

Sources reused (public, already-computed): musinsa/29cm real-time ranking + search trend feeds,
synced from the author's own already-public GitHub Pages data endpoint.
Sources fetched fresh (public APIs, no auth): weather (open-meteo), fashion news (Google News RSS).
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

UPSTREAM_BASE = "https://dlgksgml1158-commits.github.io/musinsa-dashboard/data"
PUBLIC_UPSTREAM_FILES = [
    "musinsa.json",
    "29cm.json",
    "musinsa_search_trends.json",
    "naver_trends.json",
]

HEADERS = {"User-Agent": "musinsa-fashion-dashboard-bot"}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def fetch_json(url):
    return json.loads(fetch(url))


def fetch_text(url):
    return fetch(url).decode("utf-8", errors="replace")


def sync_public_upstream_files():
    for name in PUBLIC_UPSTREAM_FILES:
        try:
            data = fetch_json(f"{UPSTREAM_BASE}/{name}?t={int(time.time() * 1000)}")
            (DATA_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))
            print(f"synced {name}")
        except Exception as e:
            print(f"failed {name}: {e}")


WMO = {
    0: "맑음", 1: "대체로 맑음", 2: "부분적으로 흐림", 3: "흐림",
    45: "안개", 48: "짙은 안개",
    51: "가벼운 이슬비", 53: "이슬비", 55: "강한 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비",
    71: "약한 눈", 73: "눈", 75: "폭설",
    80: "약한 소나기", 81: "소나기", 82: "강한 소나기",
    95: "뇌우",
}


def fetch_weather():
    lat, lon = 37.5665, 126.978
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,weather_code,wind_speed_10m,precipitation"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        "&timezone=Asia%2FSeoul&forecast_days=7"
    )
    data = fetch_json(url)

    days = []
    for i, date in enumerate(data["daily"]["time"]):
        code = data["daily"]["weather_code"][i]
        days.append({
            "date": date,
            "tMax": data["daily"]["temperature_2m_max"][i],
            "tMin": data["daily"]["temperature_2m_min"][i],
            "precipProb": data["daily"]["precipitation_probability_max"][i],
            "weatherCode": code,
            "weatherLabel": WMO.get(code, "-"),
        })

    avg_max = round(sum(d["tMax"] for d in days) / len(days))
    avg_min = round(sum(d["tMin"] for d in days) / len(days))
    rain_days = sum(1 for d in days if d["precipProb"] >= 40)
    hot_days = sum(1 for d in days if d["tMax"] >= 28)

    suggestions = []
    if hot_days >= 4:
        suggestions.append({"item": "반팔 티셔츠 / 린넨 셔츠", "reason": f"주간 최고 {avg_max}°C 내외 — 통기성 좋은 여름 상의 수요 증가 예상"})
        suggestions.append({"item": "반바지 / 숏 팬츠", "reason": "무더운 날씨로 시원한 하의 카테고리 인기 상승 전망"})
    if rain_days >= 2:
        suggestions.append({"item": "방수 재킷 / 우비", "reason": f"이번 주 {rain_days}일 강수 확률 40%↑ — 우천 대비 아이템 수요 기대"})
    if avg_max >= 27:
        suggestions.append({"item": "선글라스 / 모자", "reason": "맑고 더운 날 지속 — 자외선 차단 잡화 판매 상승 기대"})

    code = data["current"]["weather_code"]
    return {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "city": "서울",
        "current": {
            "temp": data["current"]["temperature_2m"],
            "weatherLabel": WMO.get(code, "-"),
            "windSpeed": data["current"]["wind_speed_10m"],
            "precipitation": data["current"]["precipitation"],
        },
        "week": {
            "avgMax": avg_max,
            "avgMin": avg_min,
            "rainDays": rain_days,
            "summary": f"{days[0]['date']} ~ {days[-1]['date']} 서울 주간 날씨: 평균 최고 {avg_max}°C, 최저 {avg_min}°C. 비 오는 날 {rain_days}일 포함.",
        },
        "days": days,
        "suggestions": suggestions,
    }


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

    (DATA_DIR / "meta.json").write_text(
        json.dumps({"updatedAt": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
