import os
import requests
import json
import time
import random
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

# Load environment variables
load_dotenv()

# Configuration
GEORGIA_NEWS_URL = "https://www.georgia-news-japan.online/"
TWITTER_API_URL = "https://api.twitter.com/2/tweets"
MAX_TWEET_LENGTH = 280
POSTED_ARTICLES_FILE = "posted_articles_simple.json"
MAX_RETRIES = 3
HOURS_BETWEEN_POSTS = 1  # Post every hour

# Debug print function
def debug_print(message):
    """Print debug messages"""
    print(f"[DEBUG] {message}")

def load_posted_articles():
    """Load the list of previously posted articles"""
    try:
        if os.path.exists(POSTED_ARTICLES_FILE):
            with open(POSTED_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                debug_print(f"Loaded {len(data['posted_urls'])} posted articles")
                return data
        
        # If file doesn't exist, create a new one
        debug_print("No posted articles file found, creating new record")
        new_data = {
            "posted_urls": [],
            "posted_titles": [],
            "last_post_time": 0
        }
        
        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
            
        return new_data
    except Exception as e:
        debug_print(f"Error loading posted articles: {str(e)}")
        return {
            "posted_urls": [],
            "posted_titles": [],
            "last_post_time": 0
        }

def save_posted_articles(posted_data):
    """Save the list of posted articles"""
    try:
        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted_data, f, ensure_ascii=False, indent=2)
        debug_print(f"Saved {len(posted_data['posted_urls'])} posted articles")
    except Exception as e:
        debug_print(f"Error saving posted articles: {str(e)}")

def get_articles():
    """Scrape articles from Georgia News Japan with retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            debug_print(f"Fetching articles (attempt {attempt+1}/{MAX_RETRIES})...")
            response = requests.get(GEORGIA_NEWS_URL, timeout=15)
            
            if response.status_code != 200:
                debug_print(f"Failed to fetch articles, status code: {response.status_code}")
                time.sleep(2)
                continue
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            articles = []
            links = soup.find_all('a', href=True)
            debug_print(f"Found {len(links)} links on the page")
            
            for link in links:
                url = link['href']
                title = link.get_text(strip=True)
                
                if not title or len(title) < 10:
                    continue
                    
                if not url.startswith('http'):
                    url = f"{GEORGIA_NEWS_URL.rstrip('/')}{url}"
                
                if '/post/' in url:
                    articles.append({'title': title, 'url': url})
            
            debug_print(f"Found {len(articles)} potential articles")
            return articles
            
        except Exception as e:
            debug_print(f"Error fetching articles (attempt {attempt+1}): {str(e)}")
            time.sleep(2)
    
    debug_print("All attempts to fetch articles failed")
    return []

def get_article_content(url):
    """Scrape the content of an article with retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            debug_print(f"Fetching article content (attempt {attempt+1}/{MAX_RETRIES}): {url}")
            response = requests.get(url, timeout=15)
    
            if response.status_code != 200:
                debug_print(f"Failed to fetch article, status code: {response.status_code}")
                time.sleep(2)
                continue
    
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to find paragraphs
            paragraphs = soup.find_all('p')
            if paragraphs:
                valid_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
                if valid_paragraphs:
                    content = ' '.join(valid_paragraphs)
                    debug_print(f"Found content: {len(content)} chars")
                    return content
                    
            # If no paragraphs found, try to find any div with substantial text
            divs = soup.find_all('div')
            div_texts = []
            for div in divs:
                text = div.get_text(strip=True)
                if len(text) > 100:
                    div_texts.append(text)
            if div_texts:
                content = max(div_texts, key=len)
                debug_print(f"Found content using divs: {len(content)} chars")
                return content
                
            debug_print("Could not extract article content")
            time.sleep(2)
                
        except Exception as e:
            debug_print(f"Error fetching article content (attempt {attempt+1}): {str(e)}")
            time.sleep(2)
    
    debug_print("All attempts to fetch article content failed")
    return None

def create_tweet(title, url):
    """Create a tweet with the article title and URL"""
    # Make sure the title ends with a proper sentence ending
    if not (title.endswith('。') or title.endswith('.') or 
            title.endswith('!') or title.endswith('?') or
            title.endswith('！') or title.endswith('？')):
        title = title + '。'
    
    # Ensure the title is not too long
    max_title_length = MAX_TWEET_LENGTH - len(url) - 5
    if len(title) > max_title_length:
        # Find the last sentence ending within the limit
        truncated = title[:max_title_length]
        
        # Look for sentence endings
        last_jp_period = truncated.rfind('。')
        last_en_period = truncated.rfind('.')
        last_question = truncated.rfind('？')
        last_exclamation = truncated.rfind('！')
        last_q_mark = truncated.rfind('?')
        last_excl_mark = truncated.rfind('!')
        
        end_positions = [pos for pos in [last_jp_period, last_en_period, last_question, 
                                        last_exclamation, last_q_mark, last_excl_mark] if pos > 0]
        
        if end_positions:
            # Use the latest sentence ending
            last_end = max(end_positions)
            title = title[:last_end + 1]
        else:
            # If no sentence ending found, just truncate and add a period
            title = truncated.strip() + '。'
    
    # Create the tweet
    tweet_text = f"{title}\n\n{url}"
    return tweet_text

def post_to_twitter(tweet_text):
    """Post a tweet using Twitter API v2 with improved error handling"""
    for attempt in range(MAX_RETRIES):
        try:
            debug_print(f"Authenticating with Twitter (attempt {attempt+1}/{MAX_RETRIES})...")
            
            auth = OAuth1(
                os.getenv('X_API_KEY'),
                os.getenv('X_API_SECRET'),
                os.getenv('X_ACCESS_TOKEN'),
                os.getenv('X_ACCESS_SECRET')
            )
            
            debug_print("Posting tweet...")
            debug_print(f"Tweet length: {len(tweet_text)} characters")
            debug_print(f"Full tweet content:\n{tweet_text}")
            
            payload = {
                "text": tweet_text
            }
            
            response = requests.post(
                TWITTER_API_URL,
                auth=auth,
                json=payload,
                timeout=20
            )
            
            debug_print(f"Twitter response: {response.status_code} - {response.text}")
            
            # Check for duplicate content error
            if response.status_code == 403 and "duplicate content" in response.text.lower():
                debug_print("Twitter rejected tweet as duplicate content")
                return False, "duplicate"
                
            # Check for rate limit error
            if response.status_code == 429:
                debug_print("Twitter rate limit reached, waiting before retry...")
                time.sleep(60)
                continue
                
            return response.status_code == 201, None
            
        except Exception as e:
            debug_print(f"Twitter posting error (attempt {attempt+1}): {str(e)}")
            time.sleep(5)
    
    debug_print("All attempts to post to Twitter failed")
    return False, "error"

def update_posted_data(article, posted_data):
    """Update the posted data with a new article"""
    url = article['url']
    title = article['title']
    
    # Add URL to posted list (keep last 100)
    if len(posted_data['posted_urls']) >= 100:
        posted_data['posted_urls'].pop(0)
    posted_data['posted_urls'].append(url)
    
    # Add title to posted list (keep last 100)
    if len(posted_data['posted_titles']) >= 100:
        posted_data['posted_titles'].pop(0)
    posted_data['posted_titles'].append(title)
    
    # Update last post time
    posted_data['last_post_time'] = time.time()
    
    # Save updated data
    save_posted_articles(posted_data)

def main():
    debug_print("=" * 50)
    debug_print("Starting Georgia News Bot (SIMPLE VERSION)...")
    debug_print("=" * 50)

    # Verify environment variables
    required_vars = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET']
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        debug_print(f"Missing required environment variables: {', '.join(missing_vars)}")
        return
    
    # Load previously posted articles
    posted_data = load_posted_articles()
    
    # Check if enough time has passed since the last post
    current_time = time.time()
    time_since_last_post = current_time - posted_data.get('last_post_time', 0)
    hours_since_last_post = time_since_last_post / 3600
    
    if hours_since_last_post < HOURS_BETWEEN_POSTS:
        debug_print(f"Only {hours_since_last_post:.1f} hours since last post. Minimum is {HOURS_BETWEEN_POSTS} hours. Skipping.")
        return
    
    # Get latest articles
    articles = get_articles()
    if not articles:
        debug_print("No articles found.")
        return
    
    # Filter out articles that have already been posted
    new_articles = []
    for article in articles:
        if article['url'] not in posted_data['posted_urls'] and article['title'] not in posted_data['posted_titles']:
            new_articles.append(article)
    
    if not new_articles:
        debug_print("No new articles to post.")
        return
    
    # Randomly select an article to post (to avoid always posting the same one)
    selected_article = random.choice(new_articles)
    debug_print(f"Selected article: {selected_article['title']}")
    
    # Create tweet
    tweet_text = create_tweet(selected_article['title'], selected_article['url'])
    
    debug_print("Final tweet content:")
    debug_print(tweet_text)
    
    # Post to Twitter
    success, error_type = post_to_twitter(tweet_text)
    
    if success:
        debug_print("Successfully posted to Twitter!")
        update_posted_data(selected_article, posted_data)
    else:
        if error_type == "duplicate":
            debug_print("Twitter rejected as duplicate content. Trying with a modified tweet...")
            
            # Try with a slightly modified title
            modified_title = selected_article['title'] + "について。"
            modified_tweet = create_tweet(modified_title, selected_article['url'])
            
            debug_print(f"Modified tweet:\n{modified_tweet}")
            
            # Try posting again
            retry_success, _ = post_to_twitter(modified_tweet)
            if retry_success:
                debug_print("Successfully posted modified tweet!")
                update_posted_data(selected_article, posted_data)
            else:
                debug_print("Failed to post modified tweet. Skipping this article.")
        else:
            debug_print(f"Failed to post about: {selected_article['title']}")

if __name__ == "__main__":
    main()
