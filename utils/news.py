
import feedparser
import urllib.parse
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def fetch_company_news(company_name: str, limit: int = 5):
    """
    Fetch news for a specific company using Google News RSS.
    
    Args:
        company_name (str): Name of the company to search for.
        limit (int): Maximum number of news items to return.
        
    Returns:
        list: List of dictionaries containing news item details (title, link, date, source).
    """
    try:
        # Construct search query: Company Name + (Stock OR Financials OR Performance)
        # Using simplified query for better hit rate
        query = f"{company_name}"
        encoded_query = urllib.parse.quote(query)
        
        # Google News RSS URL (Japan)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ja&gl=JP&ceid=JP:ja"
        
        logger.info(f"Fetching news for {company_name}: {rss_url}")
        
        # Parse RSS feed
        feed = feedparser.parse(rss_url)
        
        news_items = []
        for entry in feed.entries[:limit]:
            # Extract basic info
            item = {
                "title": entry.title,
                "link": entry.link,
                "published": entry.published if "published" in entry else "",
                "source": entry.source.title if "source" in entry else "Google News",
                "summary": entry.summary if "summary" in entry else ""
            }
            
            # Formatting Date
            # Google RSS date format: "Fri, 27 Dec 2024 07:00:00 GMT"
            formatted_date = ""
            if "published" in entry:
                try:
                    # Parse GMT date string
                    dt = datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %Z")
                    formatted_date = f"{dt.year}年{dt.month}月{dt.day}日"
                except Exception:
                    # Fallback or keep original if parsing fails
                    formatted_date = entry.published

            item["published"] = formatted_date
            news_items.append(item)
            
        return news_items

    except Exception as e:
        logger.error(f"Error fetching news for {company_name}: {e}")
        return []
