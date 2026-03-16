import os
import asyncio
import requests
import subprocess
import json
import feedparser
import tempfile
import random
import urllib.request
import edge_tts
from google.oauth2.credentials import Credentials
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

def fetch_news():
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                articles.append({'title': entry.get('title',''), 'summary': entry.get('summary','')[:300]})
        except Exception as e:
            print(f'RSS error {url}: {e}')
    return articles[:20]

def generate_scripts(articles):
    articles_text = '\n'.join([f"{i+1}. {a['title']}: {a['summary']}" for i, a in enumerate(articles[:15])])
    prompt = f"""You are a YouTube Shorts script writer for a finance news channel.
Here are today headlines:
{articles_text}

Pick the {VIDEOS_PER_RUN} most engaging stories. For each write a YouTube Shorts script (max 150 words, ~55 seconds).
Rules: Start with STRONG hook. Simple energetic language. End with: Follow for more finance news!
Return ONLY a JSON array, no markdown, no other text:
[{{"title":"catchy title max 60 chars","script":"full script here","tags":["finance","money","investing"],"search_query":"pexels search term"}}]"""

    payload = json.dumps({"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}).encode()
    req = urllib.request.Request(
        'https://api.groq.com/openai/v1/chat/completions',
        data=payload,
        headers={'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    text = result['choices'][0]['message']['content'].strip()
    if '```' in text:
        parts = text.split('```')
        text = parts[1] if len(parts) > 1 else parts[0]
        if text.startswith('json'):
            text = text[4:]
    return json.loads(text.strip())

async def generate_audio(script, output_path):
    communicate = edge_tts.Communicate(script, voice='en-US-GuyNeural', rate='+10%')
    await communicate.save(output_path)

def download_pexels_video(query, output_path):
    headers = {'Authorization': PEXELS_API_KEY}
    url = f'https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=10&size=medium'
    resp = requests.get(url, headers=headers)
    data = resp.json()
    videos = data.get('videos', [])
    if not videos:
        resp = requests.get('https://api.pexels.com/videos/search?query=finance&orientation=portrait&per_page=10', headers=headers)
        videos = resp.json().get('videos', [])
    video = random.choice(videos[:5])
    video_files = sorted([f for f in video['video_files'] if f.get('quality') in ['hd','sd']], key=lambda x: x.get('width',0), reverse=True)
    r = requests.get(video_files[0]['link'], stream=True)
    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

def format_time(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def create_shorts_video(video_path, audio_path, script, output_path):
    result = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',audio_path], capture_output=True, text=True)
    duration = float(result.stdout.strip())
    words = script.split()
    chunks, chunk = [], []
    for word in words:
        chunk.append(word)
        if len(chunk) >= 7:
            chunks.append(' '.join(chunk))
            chunk = []
    if chunk:
        chunks.append(' '.join(chunk))
    srt_path = audio_path.replace('.mp3', '.srt')
    tpc = duration / len(chunks) if chunks else 1
    with open(srt_path, 'w') as f:
        for i, txt in enumerate(chunks):
            f.write(f"{i+1}\n{format_time(i*tpc)} --> {format_time((i+1)*tpc)}\n{txt}\n\n")
    cmd = [
        'ffmpeg','-y','-stream_loop','-1','-i',video_path,'-i',audio_path,
        '-vf', "crop=ih*9/16:ih,scale=1080:1920,subtitles=" + srt_path + ":force_style='FontSize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Bold=1'",
        '-c:v','libx264','-preset','fast','-crf','23',
        '-c:a','aac','-b:a','128k',
        '-t',str(duration),'-shortest',output_path
    ]
    subprocess.run(cmd, check=True)

def get_youtube_service():
    creds = Credentials(
        token=None, refresh_token=YOUTUBE_REFRESH_TOKEN,
        client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET,
        token_uri='https://oauth2.googleapis.com/token'
    )
    return build('youtube', 'v3', credentials=creds)

def upload_to_youtube(youtube, video_path, title, tags):
    body = {
        'snippet': {
            'title': title,
            'description': 'Daily finance news in 60 seconds!\n\n#Shorts #Finance #Money #Investing #StockMarket',
            'tags': tags + ['shorts','finance','money','investing'],
            'categoryId': '25',
        },
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
    }
    media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f'Upload {int(status.progress() * 100)}%')
    print(f'Uploaded: https://youtube.com/shorts/{response["id"]}')
    return response['id']

async def main():
    print('Fetching news...')
    articles = fetch_news()
    print(f'Found {len(articles)} articles')
    print('Generating scripts with Groq (Llama)...')
    scripts = generate_scripts(articles)
    print(f'Generated {len(scripts)} scripts')
    youtube = get_youtube_service()
    for i, item in enumerate(scripts):
        print(f'--- Video {i+1}/{len(scripts)}: {item["title"]} ---')
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, 'audio.mp3')
            video_raw  = os.path.join(tmpdir, 'raw.mp4')
            video_out  = os.path.join(tmpdir, 'output.mp4')
            print('Generating audio...')
            await generate_audio(item['script'], audio_path)
            print('Downloading Pexels video...')
            download_pexels_video(item.get('search_query', random.choice(PEXELS_QUERIES)), video_raw)
            print('Creating Shorts video...')
            create_shorts_video(video_raw, audio_path, item['script'], video_out)
            print('Uploading to YouTube...')
            upload_to_youtube(youtube, video_out, item['title'], item['tags'])
    print('All done!')

if __name__ == '__main__':
    asyncio.run(main())
