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
ENABLE_URL_SHORTENING = False  # Completely disabled

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
    """Scrape the content of an article from georgia-news-japan.online"""
    try:
        debug_print(f"Fetching article content from: {url}")
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            debug_print(f"Failed to fetch article, status code: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Save HTML for debugging
        with open("debug_article_raw.html", "w", encoding="utf-8") as f:
            f.write(response.text)

        # Based on the website structure, the article content is in a div with class "prose prose-gray max-w-none"
        # This is specific to georgia-news-japan.online
        content_div = soup.select_one('.prose.prose-gray.max-w-none')

        if content_div:
            # Get all paragraphs from the content div
            paragraphs = content_div.find_all('p')
            if paragraphs:
                # Extract text from each paragraph
                paragraph_texts = [p.get_text(strip=True) for p in paragraphs]
                # Filter out empty paragraphs
                paragraph_texts = [p for p in paragraph_texts if p]

                if paragraph_texts:
                    # Join paragraphs with newlines for better readability
                    content = '\n'.join(paragraph_texts)
                    debug_print(f"Found {len(paragraph_texts)} paragraphs in article content")
                    return content

        # Fallback: Try to find the article element and extract all text
        article_element = soup.select_one('article')
        if article_element:
            # Get all paragraphs from the article
            paragraphs = article_element.find_all('p')
            if paragraphs:
                paragraph_texts = [p.get_text(strip=True) for p in paragraphs]
                paragraph_texts = [p for p in paragraph_texts if p]

                if paragraph_texts:
                    content = '\n'.join(paragraph_texts)
                    debug_print(f"Fallback: Found {len(paragraph_texts)} paragraphs in article element")
                    return content

        # Second fallback: Try to find any div with class containing "content"
        content_divs = soup.select('[class*="content"]')
        for div in content_divs:
            paragraphs = div.find_all('p')
            if paragraphs and len(paragraphs) >= 2:  # At least 2 paragraphs to be considered content
                paragraph_texts = [p.get_text(strip=True) for p in paragraphs]
                paragraph_texts = [p for p in paragraph_texts if p and len(p) > 20]  # Only substantial paragraphs

                if paragraph_texts:
                    content = '\n'.join(paragraph_texts)
                    debug_print(f"Second fallback: Found {len(paragraph_texts)} paragraphs in content div")
                    return content

        # Last resort: Just get all paragraphs from the page
        all_paragraphs = soup.find_all('p')
        if all_paragraphs:
            paragraph_texts = [p.get_text(strip=True) for p in all_paragraphs]
            paragraph_texts = [p for p in paragraph_texts if p and len(p) > 30]  # Only substantial paragraphs

            if paragraph_texts:
                content = '\n'.join(paragraph_texts)
                debug_print(f"Last resort: Found {len(paragraph_texts)} paragraphs on page")
                return content

        debug_print("Could not extract article content using any method")
        # Save HTML for debugging
        with open("debug_article.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        debug_print("Saved article HTML to debug_article.html for inspection")
        return None

    except Exception as e:
        debug_print(f"Error fetching article content: {str(e)}")
        return None

def generate_summary_from_content(title, content=None):
    """Generate a summary without using external APIs"""
    try:
        debug_print(f"Generating summary from content (length: {len(content) if content else 0})")

        # If no content or very short content, just use the title with a period
        if not content or len(content) < 20:
            debug_print("Content too short, using title")
            # Add a period if the title doesn't end with one
            if not title.endswith('。') and not title.endswith('.'):
                return f"{title}。"
            return title

        # Extract complete sentences from the content
        content = content.strip()

        # Split content into paragraphs if it contains newlines
        paragraphs = content.split('\n')
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        # Get the first few paragraphs to work with
        working_paragraphs = []
        total_length = 0
        for p in paragraphs:
            if total_length < 500:  # Get enough content to work with
                working_paragraphs.append(p)
                total_length += len(p)
            else:
                break

        if not working_paragraphs:
            debug_print("No valid paragraphs found, using title")
            if not title.endswith('。') and not title.endswith('.'):
                return f"{title}。"
            return title

        # Join the working paragraphs
        working_text = ' '.join(working_paragraphs)
        debug_print(f"Working with text: {working_text[:100]}...")

        # Find complete sentences
        sentences = []
        start = 0

        # Extract sentences until we have enough for a good summary
        while start < len(working_text) and len(''.join(sentences)) < 200:
            # Find the next sentence end (Japanese period)
            jp_end = working_text.find('。', start)
            # Find the next western period
            en_end = working_text.find('.', start)

            # Determine which end to use
            if jp_end != -1 and (en_end == -1 or jp_end < en_end):
                next_end = jp_end
            elif en_end != -1:
                next_end = en_end
            else:
                # No more sentence endings
                break

            # Extract the sentence (including the period)
            sentence = working_text[start:next_end+1]

            if len(sentence) > 10:  # Only add if it's a substantial sentence
                sentences.append(sentence)

            # Move to the next sentence
            start = next_end + 1

        if sentences:
            # Join the sentences into a summary
            summary = ''.join(sentences)

            # Ensure it's not too long (max 200 chars)
            if len(summary) > 200:
                # Find the last complete sentence that fits
                last_jp_period = summary[:200].rfind('。')
                last_en_period = summary[:200].rfind('.')
                last_period = max(last_jp_period, last_en_period)

                if last_period > 0:
                    summary = summary[:last_period+1]
                else:
                    # If no complete sentence fits, just use the first sentence
                    if len(sentences) > 0:
                        summary = sentences[0]
                    else:
                        # Last resort: use the title with a period
                        if not title.endswith('。') and not title.endswith('.'):
                            summary = f"{title}。"
                        else:
                            summary = title

            debug_print(f"Generated summary: {summary}")
            return summary
        else:
            # If no complete sentences found, use the title with a period
            debug_print("No complete sentences found, using title")
            if not title.endswith('。') and not title.endswith('.'):
                return f"{title}。"
            return title
    except Exception as e:
        debug_print(f"Local summarization error: {str(e)}")
        # Return title with a period
        if not title.endswith('。') and not title.endswith('.'):
            return f"{title}。"
        return title

def summarize_article(title, url):
    """Generate summary using OpenRouter API with article content, with fallback"""
    try:
        debug_print(f"Summarizing article: {title[:50]}...")

        # Get the article content
        content = get_article_content(url)

        # Check if OpenRouter API key is available
        if not os.getenv('OPENROUTER_API_KEY'):
            debug_print("No OpenRouter API key found, using local summarization")
            return generate_summary_from_content(title, content)

        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Georgia News Bot",
            "Content-Type": "application/json"
        }

        # Use content if available, otherwise just use the title
        if content:
            prompt = f"""この記事を簡潔に要約してください。以下の条件を守ってください：
1. 200文字以内で完結させる
2. 必ず完全な文で終わらせる（文の途中で切れないこと）
3. 「最新」や「【ジョージア最新情報】」などの接頭辞は付けない
4. 丁寧語を使用する
5. ハッシュタグは使用しない
6. 記事の主要な情報を含める

タイトル: {title}

内容: {content[:2000]}"""
        else:
            prompt = f"""この記事のタイトルから内容を推測して要約してください。以下の条件を守ってください：
1. 200文字以内で完結させる
2. 必ず完全な文で終わらせる（文の途中で切れないこと）
3. 「最新」や「【ジョージア最新情報】」などの接頭辞は付けない
4. 丁寧語を使用する
5. ハッシュタグは使用しない

タイトル: {title}"""

        payload = {
            "model": "meta-llama/llama-4-maverick:free",
            "messages": [{
                "role": "user",
                "content": prompt
            }]
        }

        try:
            response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            debug_print(f"OpenRouter response: {data}")

            if 'choices' in data and data['choices']:
                return data['choices'][0]['message']['content']
        except requests.exceptions.HTTPError as e:
            debug_print(f"OpenRouter HTTP Error: {e.response.status_code} - {e.response.text}")
            return generate_summary_from_content(title, content)
        except Exception as e:
            debug_print(f"OpenRouter API error: {str(e)}")
            return generate_summary_from_content(title, content)

        return generate_summary_from_content(title, content)

    except Exception as e:
        debug_print(f"Summarization error: {str(e)}")

    return f"{title}"

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
    # Skip URL shortening if disabled
    if not ENABLE_URL_SHORTENING:
        debug_print("URL shortening is disabled")
        return url

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
    debug_print("=" * 50)
    debug_print("Starting Georgia News Bot...")
    debug_print("=" * 50)

    # Verify environment variables
    required_vars = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET']

    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        debug_print(f"Missing required environment variables: {', '.join(missing_vars)}")
        return

    if not os.getenv('OPENROUTER_API_KEY'):
        debug_print("OpenRouter API key not found, will use local summarization")
    else:
        debug_print("OpenRouter API key found, will use AI summarization")

    debug_print("URL shortening is " + ("enabled" if ENABLE_URL_SHORTENING else "disabled"))
    debug_print("-" * 50)

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

    debug_print("-" * 50)
    debug_print(f"Selected article: {selected_article['title']}")
    debug_print(f"URL: {selected_article['url']}")

    # Generate summary
    debug_print("Generating summary...")
    summary = summarize_article(selected_article['title'], selected_article['url'])
    debug_print(f"Generated summary: {summary}")

    # Use the original URL directly
    article_url = selected_article['url']
    debug_print(f"Using URL: {article_url}")

    # For Twitter, we need to make sure the URL is shortened
    # Twitter t.co shortener will make all URLs 23 characters
    TWITTER_URL_LENGTH = 23

    # Calculate the maximum length for the summary
    # 280 (max tweet) - 23 (shortened URL) - 2 (newlines) = 255
    max_summary_length = MAX_TWEET_LENGTH - TWITTER_URL_LENGTH - 2

    # If summary is too long, truncate it to a complete sentence
    if len(summary) > max_summary_length:
        debug_print(f"Summary too long ({len(summary)} chars), truncating to {max_summary_length} chars")

        # Find the last complete sentence that fits
        truncated_summary = summary[:max_summary_length]

        # Look for Japanese period
        last_jp_period = truncated_summary.rfind('。')
        # Look for Western period
        last_en_period = truncated_summary.rfind('.')

        # Use the latest period found
        last_period = max(last_jp_period, last_en_period)

        if last_period > 0:
            # Use the complete sentence
            summary = summary[:last_period+1]
            debug_print(f"Truncated to last sentence end at position {last_period}")
        else:
            # If no period found, just truncate without ellipsis
            summary = truncated_summary
            debug_print("No sentence end found, truncated without ellipsis")

    # Prepare tweet text
    tweet_text = f"{summary}\n\n{article_url}"
    debug_print("-" * 50)

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