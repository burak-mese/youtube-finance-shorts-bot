import os
import asyncio
import requests
import subprocess
import json
import feedparser
import tempfile
import random
import base64
import edge_tts
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

GROQ_API_KEY          = os.environ['GROQ_API_KEY']
PEXELS_API_KEY        = os.environ['PEXELS_API_KEY']
YOUTUBE_CLIENT_ID     = os.environ['YOUTUBE_CLIENT_ID']
YOUTUBE_CLIENT_SECRET = os.environ['YOUTUBE_CLIENT_SECRET']
YOUTUBE_REFRESH_TOKEN = os.environ['YOUTUBE_REFRESH_TOKEN']

VIDEOS_PER_RUN = 6

RSS_FEEDS = [
    'https://feeds.reuters.com/reuters/businessNews',
    'https://finance.yahoo.com/news/rssindex',
    'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
    'https://www.cnbc.com/id/10000664/device/rss/rss.html',
]

PEXELS_QUERIES = ['stock market trading','financial charts','wall street','business economy','investment money']

# ── 1. FETCH NEWS ─────────────────────────────────────────────────────────────
def fetch_news():
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                articles.append({
                    'title': entry.get('title', ''),
                    'summary': entry.get('summary', '')[:300]
                })
        except Exception as e:
            print(f'RSS error {url}: {e}')
    return articles[:20]

# ── 2. GENERATE SCRIPTS (Groq / Llama) ───────────────────────────────────────
def generate_scripts(articles):
    articles_text = '\n'.join([
        f"{i+1}. {a['title']}: {a['summary']}"
        for i, a in enumerate(articles[:15])
    ])
    prompt = f"""You are a YouTube Shorts script writer for a finance news channel.
Here are today's headlines:
{articles_text}

Pick the {VIDEOS_PER_RUN} most engaging, viral-worthy stories.
For each story write a YouTube Shorts script (max 150 words, ~55 seconds when spoken).

Rules:
- Start with a STRONG hook that grabs attention in the first 2 seconds
- Use simple, energetic, conversational language
- Include 1-2 specific numbers/stats if available
- End with exactly: "Follow for daily finance news!"
- Make viewers feel urgency

Return ONLY a valid JSON array, no markdown, no other text:
[{{"title":"catchy YouTube title max 60 chars","script":"full script","tags":["finance","money","investing"],"search_query":"pexels video search term","emoji":"relevant emoji"}}]"""

    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8
    })
    resp = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, data=payload)
    if resp.status_code != 200:
        raise Exception(f'Groq API error {resp.status_code}: {resp.text}')
    result = resp.json()
    text = result['choices'][0]['message']['content'].strip()
    if '```' in text:
        parts = text.split('```')
        text = parts[1] if len(parts) > 1 else parts[0]
        if text.startswith('json'):
            text = text[4:]
    return json.loads(text.strip())

# ── 3. GENERATE AUDIO ─────────────────────────────────────────────────────────
async def generate_audio(script, output_path):
    communicate = edge_tts.Communicate(script, voice='en-US-GuyNeural', rate='+10%')
    await communicate.save(output_path)

# ── 4. DOWNLOAD PEXELS VIDEO ──────────────────────────────────────────────────
def download_pexels_video(query, output_path):
    headers = {'Authorization': PEXELS_API_KEY}
    url = f'https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=15&size=medium'
    resp = requests.get(url, headers=headers)
    data = resp.json()
    videos = data.get('videos', [])
    if not videos:
        resp = requests.get(
            'https://api.pexels.com/videos/search?query=finance&orientation=portrait&per_page=15&size=medium',
            headers=headers
        )
        videos = resp.json().get('videos', [])
    if not videos:
        raise Exception(f'No Pexels videos found for: {query}')
    video = random.choice(videos[:5])
    # Prefer files with width <= 1080 to avoid FFmpeg overflow
    good_files = [f for f in video['video_files'] if f.get('width', 9999) <= 1080]
    video_files = sorted(
        good_files if good_files else video['video_files'],
        key=lambda x: x.get('width', 0), reverse=True
    )
    r = requests.get(video_files[0]['link'], stream=True)
    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

# ── 5. CREATE THUMBNAIL ───────────────────────────────────────────────────────
def create_thumbnail(video_path, title, emoji, output_path):
    """Extract frame from video and add title text overlay as thumbnail."""
    try:
        # Extract frame at 1 second
        frame_path = output_path.replace('.jpg', '_frame.jpg')
        subprocess.run([
            'ffmpeg', '-y', '-ss', '1', '-i', video_path,
            '-vframes', '1', '-vf', 'scale=1280:720',
            frame_path
        ], check=True, capture_output=True)

        # Add text overlay using ffmpeg drawtext
        safe_title = title.replace("'", "\\'").replace(":", "\\:").replace("%", "\\%")[:40]
        subprocess.run([
            'ffmpeg', '-y', '-i', frame_path,
            '-vf', (
                f"drawtext=text='{safe_title}':"
                "fontcolor=white:fontsize=48:x=(w-text_w)/2:y=h-100:"
                "box=1:boxcolor=black@0.6:boxborderw=10"
            ),
            output_path
        ], check=True, capture_output=True)
        os.remove(frame_path)
        return output_path
    except Exception as e:
        print(f'Thumbnail creation failed: {e}')
        return None

# ── 6. CREATE SHORTS VIDEO ────────────────────────────────────────────────────
def create_shorts_video(video_path, audio_path, output_path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())

    cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1', '-i', video_path,
        '-i', audio_path,
        '-map', '0:v:0', '-map', '1:a:0',
        '-vf', 'scale=1080:1920',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-t', str(duration),
        output_path
    ]
    subprocess.run(cmd, check=True)

# ── 7. AUTO SAVE REFRESH TOKEN ────────────────────────────────────────────────
def save_refresh_token_to_github(new_token):
    github_token = os.environ.get('GITHUB_TOKEN')
    github_repo = os.environ.get('GITHUB_REPO')
    if not github_token or not github_repo:
        print('WARNING: Cannot auto-save token — GITHUB_TOKEN not set')
        return
    try:
        key_resp = requests.get(
            f'https://api.github.com/repos/{github_repo}/actions/secrets/public-key',
            headers={'Authorization': f'token {github_token}', 'Accept': 'application/vnd.github.v3+json'}
        )
        key_data = key_resp.json()
        from nacl import encoding, public
        public_key = public.PublicKey(key_data['key'].encode(), encoding.Base64Encoder())
        sealed_box = public.SealedBox(public_key)
        encrypted = base64.b64encode(sealed_box.encrypt(new_token.encode())).decode()
        requests.put(
            f'https://api.github.com/repos/{github_repo}/actions/secrets/YOUTUBE_REFRESH_TOKEN',
            headers={'Authorization': f'token {github_token}', 'Accept': 'application/vnd.github.v3+json'},
            json={'encrypted_value': encrypted, 'key_id': key_data['key_id']}
        )
        print('✅ New refresh token saved to GitHub Secrets!')
    except ImportError:
        print('WARNING: PyNaCl not installed')
    except Exception as e:
        print(f'WARNING: Could not save token: {e}')

# ── 8. GET YOUTUBE SERVICE ────────────────────────────────────────────────────
def get_youtube_service():
    creds = Credentials(
        token=None, refresh_token=YOUTUBE_REFRESH_TOKEN,
        client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET,
        token_uri='https://oauth2.googleapis.com/token'
    )
    try:
        creds.refresh(Request())
        if creds.refresh_token and creds.refresh_token != YOUTUBE_REFRESH_TOKEN:
            print('New refresh token received, saving to GitHub...')
            save_refresh_token_to_github(creds.refresh_token)
    except Exception as e:
        print(f'Token refresh note: {e}')
    return build('youtube', 'v3', credentials=creds)

# ── 9. UPLOAD TO YOUTUBE ──────────────────────────────────────────────────────
def upload_to_youtube(youtube, video_path, title, tags, thumbnail_path=None):
    description = (
        f"{title}\n\n"
        "Stay ahead of the markets! We break down the biggest finance stories "
        "every day in 60 seconds.\n\n"
        "⚡ Subscribe for daily finance news!\n"
        "📈 Stock market updates\n"
        "💰 Investing insights\n"
        "🏦 Economic analysis\n\n"
        "#Shorts #Finance #Money #Investing #StockMarket #FinanceNews"
    )
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags + ['shorts', 'finance', 'money', 'investing', 'stockmarket'],
            'categoryId': '25',
            'defaultLanguage': 'en',
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False,
            'madeForKids': False,
        }
    }
    media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True, chunksize=1024*1024)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f'  Upload {int(status.progress() * 100)}%')
    video_id = response['id']
    print(f'✅ Uploaded: https://youtube.com/shorts/{video_id}')

    # Set thumbnail if available
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype='image/jpeg')
            ).execute()
            print('✅ Thumbnail set!')
        except Exception as e:
            print(f'Thumbnail upload skipped: {e}')
    return video_id

# ── 10. MAIN ──────────────────────────────────────────────────────────────────
async def main():
    print('🚀 Starting YouTube Finance Shorts Bot...')
    print('Fetching news...')
    articles = fetch_news()
    print(f'Found {len(articles)} articles')

    print('Generating scripts with Groq (Llama)...')
    scripts = generate_scripts(articles)
    print(f'Generated {len(scripts)} scripts')

    youtube = get_youtube_service()
    success = 0

    for i, item in enumerate(scripts):
        print(f'\n--- Video {i+1}/{len(scripts)}: {item["title"]} ---')
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path     = os.path.join(tmpdir, 'audio.mp3')
                video_raw      = os.path.join(tmpdir, 'raw.mp4')
                video_out      = os.path.join(tmpdir, 'output.mp4')
                thumbnail_path = os.path.join(tmpdir, 'thumb.jpg')

                print('  😙️  Generating audio...')
                await generate_audio(item['script'], audio_path)

                print('  🎬  Downloading Pexels video...')
                download_pexels_video(
                    item.get('search_query', random.choice(PEXELS_QUERIES)),
                    video_raw
                )

                print('  ✂️   Creating Shorts video...')
                create_shorts_video(video_raw, audio_path, video_out)

                print('  🖼️   Creating thumbnail...')
                thumb = create_thumbnail(
                    video_out,
                    item['title'],
                    item.get('emoji', '📈'),
                    thumbnail_path
                )

                print('  📤  Uploading to YouTube...')
                upload_to_youtube(youtube, video_out, item['title'], item['tags'], thumb)
                success += 1

        except Exception as e:
            print(f'  ❌ ERROR on video {i+1}: {e} — skipping!')
            continue

    print(f'\n🎉 All done! {success}/{len(scripts)} videos uploaded successfully.')

if __name__ == '__main__':
    asyncio.run(main())
