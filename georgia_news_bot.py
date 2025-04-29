import os
import requests
import json
import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

# Load environment variables
load_dotenv()

# Configuration
GEORGIA_NEWS_URL = "https://www.georgia-news-japan.online/"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TWITTER_API_URL = "https://api.twitter.com/2/tweets"
MAX_TWEET_LENGTH = 280
POSTED_ARTICLES_FILE = "posted_articles.json"
ARTICLES_TO_TRACK = 20

def debug_print(message):
    """Helper function for debug output"""
    print(f"[DEBUG] {message}")

def load_posted_articles():
    """Load the list of previously posted articles"""
    try:
        if os.path.exists(POSTED_ARTICLES_FILE):
            with open(POSTED_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"posted": [], "last_posted_url": None}
    except Exception as e:
        debug_print(f"Error loading posted articles: {str(e)}")
        return {"posted": [], "last_posted_url": None}

def save_posted_articles(posted_data):
    """Save the list of posted articles"""
    try:
        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted_data, f, ensure_ascii=False, indent=2)
        debug_print(f"Saved {len(posted_data['posted'])} posted articles to {POSTED_ARTICLES_FILE}")
    except Exception as e:
        debug_print(f"Error saving posted articles: {str(e)}")

def get_articles():
    """Scrape articles from Georgia News Japan"""
    try:
        debug_print("Fetching articles...")
        response = requests.get(GEORGIA_NEWS_URL, timeout=10)
        print(f"Website status code: {response.status_code}")

        # Save HTML for debugging if needed
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        print("Saved HTML to debug_page.html for inspection")

        soup = BeautifulSoup(response.text, 'html.parser')

        articles = []
        links = soup.find_all('a', href=True)
        print(f"Found {len(links)} links on the page")

        for i, link in enumerate(links):
            url = link['href']
            title = link.get_text(strip=True)

            print(f"Link {i}: {url} - Text: {title[:50]}")

            if not title or len(title) < 10:
                continue

            if not url.startswith('http'):
                url = f"{GEORGIA_NEWS_URL.rstrip('/')}{url}"

            if '/post/' in url:
                articles.append({'title': title, 'url': url})
                debug_print(f"Found article: {title[:50]}...")

        print(f"Found {len(articles)} potential articles")
        return articles[:ARTICLES_TO_TRACK]  # Limit to configured number of articles

    except Exception as e:
        debug_print(f"Error fetching articles: {str(e)}")
        return []

def get_article_content(url):
    """Scrape the content of an article"""
    try:
        debug_print(f"Fetching article content from: {url}")
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            debug_print(f"Failed to fetch article, status code: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Look for the main content - adjust selectors based on the website structure
        content_selectors = [
            'article',
            '.post-content',
            '.entry-content',
            '.content',
            'main'
        ]

        content = None
        for selector in content_selectors:
            content_element = soup.select_one(selector)
            if content_element:
                content = content_element.get_text(strip=True)
                break

        if not content:
            # Fallback: try to get all paragraphs
            paragraphs = soup.find_all('p')
            if paragraphs:
                content = ' '.join([p.get_text(strip=True) for p in paragraphs])

        if content:
            debug_print(f"Successfully extracted content ({len(content)} chars)")
            return content
        else:
            debug_print("Could not extract article content")
            return None

    except Exception as e:
        debug_print(f"Error fetching article content: {str(e)}")
        return None

def summarize_article(title, url):
    """Generate summary using OpenRouter API with article content"""
    try:
        debug_print(f"Summarizing article: {title[:50]}...")

        # Get the article content
        content = get_article_content(url)

        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Georgia News Bot",
            "Content-Type": "application/json"
        }

        # Use content if available, otherwise just use the title
        if content:
            prompt = f"この記事を簡潔に要約してください (200文字以内)。ツイッター投稿用です。丁寧語で、ハッシュタグは無しで。\n\nタイトル: {title}\n\n内容: {content[:2000]}"
        else:
            prompt = f"この記事を簡潔に要約してください (200文字以内)。ツイッター投稿用です。\n\nタイトル: {title}"

        payload = {
            "model": "meta-llama/llama-4-maverick:free",
            "messages": [{
                "role": "user",
                "content": prompt
            }]
        }

        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()
        debug_print(f"OpenRouter response: {data}")

        if 'choices' in data and data['choices']:
            return data['choices'][0]['message']['content']

        return f"最新: {title}"

    except requests.exceptions.HTTPError as e:
        debug_print(f"OpenRouter HTTP Error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        debug_print(f"Summarization error: {str(e)}")

    return f" {title}"

def post_to_twitter(text):
    """Post to Twitter using API v2"""
    try:
        debug_print("Authenticating with Twitter...")

        auth = OAuth1(
            os.getenv('X_API_KEY'),
            os.getenv('X_API_SECRET'),
            os.getenv('X_ACCESS_TOKEN'),
            os.getenv('X_ACCESS_SECRET')
        )

        debug_print("Posting tweet...")
        response = requests.post(
            TWITTER_API_URL,
            json={'text': text},
            auth=auth,
            headers={'Content-Type': 'application/json'},
            timeout=15
        )

        debug_print(f"Twitter response: {response.status_code} - {response.text}")

        if response.status_code == 201:
            return True

        debug_print(f"Twitter API Error: {response.text}")
        return False

    except Exception as e:
        debug_print(f"Twitter posting error: {str(e)}")
        return False

def shorten_url(url):
    """Shorten a URL using shrtco.de API with fallback to tinyurl"""
    try:
        debug_print(f"Shortening URL: {url}")
        # Try shrtco.de first
        try:
            response = requests.get(f"https://api.shrtco.de/v2/shorten?url={url}", timeout=10)
            response.raise_for_status()

            data = response.json()
            if data.get('ok'):
                short_url = data['result']['full_short_link']
                debug_print(f"Shortened URL with shrtco.de: {short_url}")
                return short_url
        except Exception as e:
            debug_print(f"shrtco.de error: {str(e)}, trying tinyurl...")

        # Fallback to tinyurl
        try:
            response = requests.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=10)
            if response.status_code == 200:
                short_url = response.text
                debug_print(f"Shortened URL with tinyurl: {short_url}")
                return short_url
        except Exception as e:
            debug_print(f"tinyurl error: {str(e)}")

        debug_print("All URL shortening attempts failed")
        return url

    except Exception as e:
        debug_print(f"Error shortening URL: {str(e)}")
        return url

def main():
    debug_print("Starting Georgia News Bot...")

    # Verify environment variables
    required_vars = ['OPENROUTER_API_KEY', 'X_API_KEY',
                    'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET']

    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        debug_print(f"Missing environment variables: {', '.join(missing_vars)}")
        return

    # Load previously posted articles
    posted_data = load_posted_articles()

    # Get latest articles
    articles = get_articles()
    if not articles:
        debug_print("No articles found.")
        return

    # Filter out articles that have already been posted
    new_articles = []
    for article in articles:
        if article['url'] not in posted_data['posted']:
            new_articles.append(article)

    if not new_articles:
        debug_print("No new articles to post.")
        return

    # Sort articles by their position in the original list
    # This ensures we post them in the order they appear on the website
    new_articles.sort(key=lambda x: articles.index(x))

    # Select the first article that's not the same as the last posted
    selected_article = None
    for article in new_articles:
        if article['url'] != posted_data['last_posted_url']:
            selected_article = article
            break

    # If all new articles are the same as the last posted, just take the first one
    if not selected_article and new_articles:
        selected_article = new_articles[0]

    if not selected_article:
        debug_print("No suitable article found to post.")
        return

    debug_print(f"Selected article: {selected_article['title']}")

    # Generate summary
    summary = summarize_article(selected_article['title'], selected_article['url'])

    # Try to shorten the URL
    short_url = shorten_url(selected_article['url'])

    # Prepare tweet text
    tweet_text = f"{summary}\n\n{short_url}"

    # Ensure tweet is within character limit
    if len(tweet_text) > MAX_TWEET_LENGTH:
        available_chars = MAX_TWEET_LENGTH - len(short_url) - 5  # 5 for "\n\n" and some buffer
        summary = summary[:available_chars] + "..."
        tweet_text = f"{summary}\n\n{short_url}"

    debug_print("Final tweet content:")
    debug_print(tweet_text)

    # Post to Twitter
    if post_to_twitter(tweet_text):
        debug_print("Successfully posted to Twitter!")

        # Update posted articles list
        if len(posted_data['posted']) >= ARTICLES_TO_TRACK:
            posted_data['posted'].pop(0)  # Remove oldest article if we've reached the limit

        posted_data['posted'].append(selected_article['url'])
        posted_data['last_posted_url'] = selected_article['url']
        save_posted_articles(posted_data)
    else:
        debug_print(f"Failed to post about: {selected_article['title']}")

if __name__ == "__main__":
    main()