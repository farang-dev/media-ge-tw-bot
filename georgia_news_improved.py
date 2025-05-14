import os
import requests
import json
import time
import hashlib
import random
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
POSTED_ARTICLES_FILE = "posted_articles_improved.json"
ARTICLES_TO_TRACK = 50  # Track more articles to better detect duplicates
MINIMUM_HOURS_BETWEEN_POSTS = 3  # At least 3 hours between posts
URL_BUFFER = 30  # Space for URL and newlines
MAX_RETRIES = 3  # Maximum number of retries for network operations

# Debug print function
def debug_print(message):
    """Print debug messages"""
    print(f"[DEBUG] {message}")

def get_content_hash(text):
    """Generate a hash of the content to detect similar articles"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def load_posted_articles():
    """Load the list of previously posted articles"""
    try:
        # First try to load from the main file
        if os.path.exists(POSTED_ARTICLES_FILE):
            with open(POSTED_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                debug_print(f"Loaded {len(data['posted'])} posted articles")
                return data

        # If file doesn't exist, create a new one
        debug_print("No posted articles file found, creating new record")
        new_data = {
            "posted": [],
            "content_hashes": [],
            "last_post_time": 0
        }

        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)

        return new_data
    except Exception as e:
        debug_print(f"Error loading posted articles: {str(e)}")
        return {
            "posted": [],
            "content_hashes": [],
            "last_post_time": 0
        }

def save_posted_articles(posted_data):
    """Save the list of posted articles"""
    try:
        with open(POSTED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(posted_data, f, ensure_ascii=False, indent=2)
        debug_print(f"Saved {len(posted_data['posted'])} posted articles")
    except Exception as e:
        debug_print(f"Error saving posted articles: {str(e)}")

def get_articles():
    """Scrape articles from Georgia News Japan with retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            debug_print(f"Fetching articles (attempt {attempt+1}/{MAX_RETRIES})...")
            response = requests.get(GEORGIA_NEWS_URL, timeout=15)
            debug_print(f"Website status code: {response.status_code}")

            if response.status_code != 200:
                debug_print(f"Failed to fetch articles, status code: {response.status_code}")
                time.sleep(2)  # Wait before retrying
                continue

            soup = BeautifulSoup(response.text, 'html.parser')

            articles = []
            links = soup.find_all('a', href=True)
            debug_print(f"Found {len(links)} links on the page")

            for i, link in enumerate(links):
                url = link['href']
                title = link.get_text(strip=True)

                if not title or len(title) < 10:
                    continue

                if not url.startswith('http'):
                    url = f"{GEORGIA_NEWS_URL.rstrip('/')}{url}"

                if '/post/' in url:
                    articles.append({'title': title, 'url': url})
                    debug_print(f"Found article: {title[:50]}...")

            debug_print(f"Found {len(articles)} potential articles")
            return articles[:ARTICLES_TO_TRACK]

        except Exception as e:
            debug_print(f"Error fetching articles (attempt {attempt+1}): {str(e)}")
            time.sleep(2)  # Wait before retrying

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
                time.sleep(2)  # Wait before retrying
                continue

            soup = BeautifulSoup(response.text, 'html.parser')

            # Try multiple approaches to extract content
            content = None

            # Try to find paragraphs
            paragraphs = soup.find_all('p')
            if paragraphs:
                # Filter out very short paragraphs (likely navigation or metadata)
                valid_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
                if valid_paragraphs:
                    content = ' '.join(valid_paragraphs)
                    debug_print(f"Found content using paragraphs: {len(valid_paragraphs)} paragraphs")

            # If no paragraphs found, try to find any div with substantial text
            if not content or len(content) < 50:
                divs = soup.find_all('div')
                div_texts = []
                for div in divs:
                    text = div.get_text(strip=True)
                    if len(text) > 100:  # Only consider divs with substantial text
                        div_texts.append(text)
                if div_texts:
                    content = max(div_texts, key=len)  # Use the longest text
                    debug_print(f"Found content using divs: {len(div_texts)} divs with substantial text")

            if content:
                debug_print(f"Successfully extracted content ({len(content)} chars)")
                debug_print(f"Content preview: {content[:100]}...")
                return content
            else:
                debug_print("Could not extract article content using any method")
                time.sleep(2)  # Wait before retrying

        except Exception as e:
            debug_print(f"Error fetching article content (attempt {attempt+1}): {str(e)}")
            time.sleep(2)  # Wait before retrying

    debug_print("All attempts to fetch article content failed")
    return None

def remove_prefixes(text):
    """Remove common prefixes from the summary"""
    prefixes = [
        "最新: ", "最新：", "最新 ", "最新",
        "【ジョージア最新情報】", "【最新情報】", "【速報】",
        "ジョージア最新: ", "ジョージア: ", "ジョージア：",
        "ジョージアニュース: ", "ジョージアニュース（", "ジョージアニュース("
    ]

    for prefix in prefixes:
        if text.startswith(prefix):
            debug_print(f"Removing prefix: '{prefix}'")
            # If the prefix contains a parenthesis, find the closing one
            if "（" in prefix or "(" in prefix:
                closing_idx = text.find("）")
                if closing_idx == -1:
                    closing_idx = text.find(")")
                if closing_idx != -1:
                    return text[closing_idx+1:].lstrip(": ")
            return text[len(prefix):].lstrip(": ")

    return text

def generate_summary(title, content):
    """Generate a summary using OpenRouter API with improved error handling"""
    try:
        debug_print(f"Generating summary for: {title[:50]}...")

        # Check if OpenRouter API key is available
        if not os.getenv('OPENROUTER_API_KEY'):
            debug_print("No OpenRouter API key found, using title as summary")
            if not title.endswith('。') and not title.endswith('.'):
                return f"{title}。"
            return title

        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Georgia News Bot",
            "Content-Type": "application/json"
        }

        # Calculate maximum summary length
        max_length = MAX_TWEET_LENGTH - URL_BUFFER

        # Use content if available, otherwise just use the title
        if content:
            prompt = f"""この記事を簡潔に要約してください。以下の条件を守ってください：
1. {max_length}文字以内で完結させる
2. 必ず完全な文で終わらせる（文の途中で切れないこと）
3. 「最新」や「【ジョージア最新情報】」などの接頭辞は絶対に付けないでください
4. 読者の興味を引く魅力的な文章で書いてください
5. ハッシュタグは使用しない
6. 記事の主要な情報を含める
7. 要約は「ジョージア」または記事の主題から始めてください
8. 文章は必ず完結させてください。途中で切れた文章は絶対に避けてください。
9. 時間や日付の情報は入れないでください。
10. 必ず文末に「。」「！」「？」などの句読点を入れて文を完結させてください。
11. 短い文章で構成し、長い複雑な文は避けてください。

タイトル: {title}

内容: {content[:2000]}"""
        else:
            prompt = f"""この記事のタイトルから内容を推測して要約してください。以下の条件を守ってください：
1. {max_length}文字以内で完結させる
2. 必ず完全な文で終わらせる（文の途中で切れないこと）
3. 「最新」や「【ジョージア最新情報】」などの接頭辞は絶対に付けないでください
4. 読者の興味を引く魅力的な文章で書いてください
5. ハッシュタグは使用しない
6. 要約は「ジョージア」または記事の主題から始めてください
7. 文章は必ず完結させてください。途中で切れた文章は絶対に避けてください。
8. 時間や日付の情報は入れないでください。
9. 必ず文末に「。」「！」「？」などの句読点を入れて文を完結させてください。
10. 短い文章で構成し、長い複雑な文は避けてください。

タイトル: {title}"""

        # Try different models in case of failure
        models = [
            "anthropic/claude-3-haiku-20240307",
            "anthropic/claude-3-sonnet-20240229",
            "meta-llama/llama-3-8b-instruct"
        ]

        for model in models:
            try:
                payload = {
                    "model": model,
                    "messages": [{
                        "role": "user",
                        "content": prompt
                    }]
                }

                debug_print(f"Trying model: {model}")
                response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
                response.raise_for_status()

                data = response.json()

                if 'choices' in data and data['choices']:
                    summary = data['choices'][0]['message']['content']
                    # Remove any prefixes that might have been added despite instructions
                    summary = remove_prefixes(summary)

                    # Verify the summary ends with a proper sentence ending
                    if not (summary.endswith('。') or summary.endswith('.') or
                            summary.endswith('!') or summary.endswith('?') or
                            summary.endswith('！') or summary.endswith('？')):
                        debug_print("Adding period to summary")
                        summary = summary + '。'

                    # Ensure the summary is not too long
                    if len(summary) > max_length:
                        debug_print(f"Summary too long ({len(summary)} chars), truncating")
                        summary = truncate_to_complete_sentence(summary, max_length)

                    debug_print(f"Final summary: {summary}")
                    return summary
            except Exception as e:
                debug_print(f"Error with model {model}: {str(e)}")
                # Continue to next model

        # All models failed, fallback to title
        debug_print("All models failed, using title as summary")
        if not title.endswith('。') and not title.endswith('.'):
            return f"{title}。"
        return title

    except Exception as e:
        debug_print(f"Summarization error: {str(e)}")
        if not title.endswith('。') and not title.endswith('.'):
            return f"{title}。"
        return title

def truncate_to_complete_sentence(text, max_length):
    """Truncate text to the last complete sentence within max_length"""
    if len(text) <= max_length:
        return text

    # Find the last sentence ending within the limit
    truncated = text[:max_length]

    # Look for sentence endings
    last_jp_period = truncated.rfind('。')
    last_en_period = truncated.rfind('.')
    last_question = truncated.rfind('？')
    last_exclamation = truncated.rfind('！')
    last_q_mark = truncated.rfind('?')
    last_excl_mark = truncated.rfind('!')

    # Find the latest sentence ending
    end_positions = [pos for pos in [last_jp_period, last_en_period, last_question,
                                     last_exclamation, last_q_mark, last_excl_mark] if pos > 0]

    if end_positions:
        # Use the latest sentence ending
        last_end = max(end_positions)
        return text[:last_end + 1]

    # If no sentence ending found, try to find a complete sentence
    # by looking at the original text and finding the last complete sentence
    # that fits within the limit
    sentences = []
    current_sentence = ""

    for char in text:
        current_sentence += char
        if char in ['。', '.', '？', '！', '?', '!']:
            sentences.append(current_sentence)
            current_sentence = ""

    # If we have complete sentences, use as many as will fit
    if sentences:
        result = ""
        for sentence in sentences:
            if len(result) + len(sentence) <= max_length:
                result += sentence
            else:
                break

        if result:
            return result

    # Last resort: just truncate and add a period
    return truncated.strip() + '。'

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
                time.sleep(60)  # Wait a minute before retrying
                continue

            return response.status_code == 201, None

        except Exception as e:
            debug_print(f"Twitter posting error (attempt {attempt+1}): {str(e)}")
            time.sleep(5)  # Wait before retrying

    debug_print("All attempts to post to Twitter failed")
    return False, "error"

def is_similar_to_posted(article, posted_data):
    """Check if an article is similar to any recently posted articles"""
    title = article['title']
    url = article['url']

    # 1. Check if URL has been posted before
    if url in posted_data['posted']:
        debug_print(f"URL already posted: {url}")
        return True

    # 2. Extract content and generate hash
    content = get_article_content(url)
    if not content:
        debug_print("Could not extract content, using title only for similarity check")
        content = title

    content_hash = get_content_hash(content)

    # 3. Check if content hash matches any previously posted article
    if content_hash in posted_data['content_hashes']:
        debug_print(f"Content hash match found: {content_hash}")
        return True

    # Not similar to any recently posted articles
    return False

def update_posted_data(article, posted_data):
    """Update the posted data with a new article"""
    url = article['url']

    # Get content and hash
    content = get_article_content(url)
    if not content:
        content = article['title']

    content_hash = get_content_hash(content)

    # Add URL to posted list
    if len(posted_data['posted']) >= ARTICLES_TO_TRACK:
        posted_data['posted'].pop(0)  # Remove oldest
    posted_data['posted'].append(url)

    # Add content hash
    if len(posted_data['content_hashes']) >= ARTICLES_TO_TRACK:
        posted_data['content_hashes'].pop(0)  # Remove oldest
    posted_data['content_hashes'].append(content_hash)

    # Update last post time
    posted_data['last_post_time'] = time.time()

    # Save updated data
    save_posted_articles(posted_data)

def create_unique_tweet(summary, url, attempt=0):
    """Create a unique tweet that won't be rejected as duplicate"""
    # First, ensure the summary is a complete sentence
    if not (summary.endswith('。') or summary.endswith('.') or
            summary.endswith('!') or summary.endswith('?') or
            summary.endswith('！') or summary.endswith('？')):
        summary = summary + '。'

    if attempt == 0:
        # First attempt - use the original summary
        tweet = f"{summary}\n\n{url}"

        # Check if it's within the character limit
        if len(tweet) <= MAX_TWEET_LENGTH:
            return tweet
        else:
            # Truncate the summary to fit
            max_summary_length = MAX_TWEET_LENGTH - len(url) - 5
            truncated_summary = truncate_to_complete_sentence(summary, max_summary_length)
            return f"{truncated_summary}\n\n{url}"

    # For subsequent attempts, make the tweet unique
    # Add a small random variation at the end of the summary
    variations = [
        "詳細はリンクから。",
        "詳しくはこちら。",
        "続きを読む。",
        "全文を読む。",
        "詳細記事はこちら。",
        "詳しい情報はリンクから。"
    ]

    # Choose a random variation
    variation = random.choice(variations)

    # Make sure the summary doesn't already end with this variation
    if not summary.endswith(variation):
        # Ensure we don't exceed the character limit
        max_length = MAX_TWEET_LENGTH - len(variation) - len(url) - 5
        truncated_summary = truncate_to_complete_sentence(summary, max_length)

        # Check if the truncated summary ends with a sentence ending
        if not (truncated_summary.endswith('。') or truncated_summary.endswith('.') or
                truncated_summary.endswith('!') or truncated_summary.endswith('?') or
                truncated_summary.endswith('！') or truncated_summary.endswith('？')):
            # Find the last sentence ending
            last_jp_period = truncated_summary.rfind('。')
            last_en_period = truncated_summary.rfind('.')
            last_question = truncated_summary.rfind('？')
            last_exclamation = truncated_summary.rfind('！')
            last_q_mark = truncated_summary.rfind('?')
            last_excl_mark = truncated_summary.rfind('!')

            end_positions = [pos for pos in [last_jp_period, last_en_period, last_question,
                                            last_exclamation, last_q_mark, last_excl_mark] if pos > 0]

            if end_positions:
                # Use the latest sentence ending
                last_end = max(end_positions)
                truncated_summary = truncated_summary[:last_end + 1]
            else:
                # If no sentence ending found, add one
                truncated_summary = truncated_summary + '。'

        return f"{truncated_summary} {variation}\n\n{url}"
    else:
        # Try again with a different variation
        return create_unique_tweet(summary, url, attempt + 1)

def main():
    debug_print("=" * 50)
    debug_print("Starting Georgia News Bot (IMPROVED VERSION)...")
    debug_print("=" * 50)

    # Verify environment variables
    required_vars = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET']

    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        debug_print(f"Missing required environment variables: {', '.join(missing_vars)}")
        return

    if not os.getenv('OPENROUTER_API_KEY'):
        debug_print("OpenRouter API key not found, will use title as summary")
    else:
        debug_print("OpenRouter API key found, will use AI summarization")

    # Load previously posted articles
    posted_data = load_posted_articles()

    # Check if enough time has passed since the last post
    current_time = time.time()
    time_since_last_post = current_time - posted_data.get('last_post_time', 0)
    hours_since_last_post = time_since_last_post / 3600

    if hours_since_last_post < MINIMUM_HOURS_BETWEEN_POSTS:
        debug_print(f"Only {hours_since_last_post:.1f} hours since last post. Minimum is {MINIMUM_HOURS_BETWEEN_POSTS} hours. Skipping.")
        return

    # Get latest articles
    articles = get_articles()
    if not articles:
        debug_print("No articles found.")
        return

    # Find the first article that's not similar to any recently posted articles
    selected_article = None
    for article in articles:
        if not is_similar_to_posted(article, posted_data):
            selected_article = article
            debug_print(f"Selected article: {article['title']}")
            break

    if not selected_article:
        debug_print("No suitable article found to post (all are similar to recent posts).")
        return

    # Get article content
    content = get_article_content(selected_article['url'])

    # Generate summary
    summary = generate_summary(selected_article['title'], content)
    debug_print(f"Generated summary: {summary}")

    # Create tweet
    tweet_text = create_unique_tweet(summary, selected_article['url'])

    # Double-check to ensure tweet is within character limit and has complete sentences
    if len(tweet_text) > MAX_TWEET_LENGTH:
        debug_print(f"Warning: Tweet too long ({len(tweet_text)} chars), truncating summary further")
        max_summary_length = MAX_TWEET_LENGTH - len(selected_article['url']) - 5
        summary = truncate_to_complete_sentence(summary, max_summary_length)
        tweet_text = f"{summary}\n\n{selected_article['url']}"

    # Verify the tweet has complete sentences
    tweet_lines = tweet_text.split('\n\n')[0]  # Get just the summary part
    if not (tweet_lines.endswith('。') or tweet_lines.endswith('.') or
            tweet_lines.endswith('!') or tweet_lines.endswith('?') or
            tweet_lines.endswith('！') or tweet_lines.endswith('？')):
        debug_print("Warning: Tweet does not end with a proper sentence ending, fixing...")
        tweet_lines = tweet_lines + '。'
        tweet_text = f"{tweet_lines}\n\n{selected_article['url']}"

    debug_print("Final tweet content:")
    debug_print(tweet_text)

    # Post to Twitter
    success, error_type = post_to_twitter(tweet_text)

    if success:
        debug_print("Successfully posted to Twitter!")

        # Update posted articles data
        update_posted_data(selected_article, posted_data)
    else:
        if error_type == "duplicate":
            debug_print("Twitter rejected as duplicate content. Trying with a modified tweet...")

            # Try up to 3 variations to make the tweet unique
            for attempt in range(1, 4):
                modified_tweet = create_unique_tweet(summary, selected_article['url'], attempt)
                debug_print(f"Modified tweet (attempt {attempt}):\n{modified_tweet}")

                # Try posting again with the modified tweet
                retry_success, retry_error = post_to_twitter(modified_tweet)
                if retry_success:
                    debug_print("Successfully posted modified tweet!")
                    update_posted_data(selected_article, posted_data)
                    break
                elif retry_error != "duplicate":
                    debug_print(f"Failed to post modified tweet with error: {retry_error}")
                    break

                debug_print(f"Modified tweet attempt {attempt} was also rejected as duplicate. Trying again...")
            else:
                debug_print("All modified tweet attempts failed. Skipping this article.")
        else:
            debug_print(f"Failed to post about: {selected_article['title']}")

if __name__ == "__main__":
    main()
