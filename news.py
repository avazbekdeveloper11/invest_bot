import requests

CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/?auth_token=public&kind=news&filter=hot&public=true"
COINGECKO_NEWS = "https://api.coingecko.com/api/v3/news"

def get_crypto_news(limit: int = 5) -> list[dict]:
    news = []
    try:
        resp = requests.get(COINGECKO_NEWS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            articles = data.get('data', [])[:limit]
            for a in articles:
                news.append({
                    'title': a.get('title', ''),
                    'url': a.get('url', ''),
                    'source': a.get('news_site', ''),
                })
    except Exception:
        pass

    if not news:
        # Fallback: RSS orqali
        try:
            rss_url = "https://cointelegraph.com/rss"
            resp = requests.get(rss_url, timeout=8)
            import re
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', resp.text)
            links = re.findall(r'<link>(https://cointelegraph\.com/[^<]+)</link>', resp.text)
            for i, (title, link) in enumerate(zip(titles[1:limit+1], links[:limit])):
                news.append({'title': title, 'url': link, 'source': 'CoinTelegraph'})
        except Exception:
            pass

    return news
