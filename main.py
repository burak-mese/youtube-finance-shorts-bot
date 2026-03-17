import os
import re
import time
import asyncio
import requests
import subprocess
import json
import feedparser
import tempfile
import random
import base64
import hashlib
import edge_tts
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import moviepy.editor as mp
import whisper_timestamped as whisper

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
    'https://feeds.bloomberg.com/markets/news.rss',
    'https://www.marketwatch.com/rss/topstories',
]

PEXELS_QUERIES = [
    'stock market trading', 'financial charts', 'wall street',
    'business economy', 'investment money'
]

VOICES = [
    ('en-US-GuyNeural',    '+10%', '+0Hz'),
    ('en-US-AndrewNeural', '+8%',  '+0Hz'),
]
_voice_idx = [0]
FONT = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'

def title_hash(title):
    return hashlib.md5(title.lower().strip()[:50].encode()).hexdigest()

def load_seen_titles():
    tok = os.environ.get('GITHUB_TOKEN')
    if tok:
        try:
            repo = os.environ.get('GITHUB_REPO', '')
            desc = 'seen-titles-' + repo.replace('/', '-')
            r = requests.get('https://api.github.com/gists', headers={'Authorization': 'token ' + tok}, params={'per_page': 10})
            if r.status_code == 200 and isinstance(r.json(), list):
                for g in r.json():
                    if isinstance(g, dict) and g.get('description') == desc:
                        c = requests.get(list(g['files'].values())[0]['raw_url']).json()
                        return set(c.get('titles', []))
        except: pass
    return set()

def save_seen_titles(titles):
    tok = os.environ.get('GITHUB_TOKEN')
    if not tok: return
    try:
        repo = os.environ.get('GITHUB_REPO', '')
        desc = 'seen-titles-' + repo.replace('/', '-')
        data = {'titles': list(titles)[-200:]}
        r = requests.get('https://api.github.com/gists', headers={'Authorization': 'token ' + tok}, params={'per_page': 10})
        gid = None
        if r.status_code == 200 and isinstance(r.json(), list):
            gid = next((g['id'] for g in r.json() if isinstance(g, dict) and g.get('description') == desc), None)
        gd = {'description': desc, 'public': False, 'files': {'seen.json': {'content': json.dumps(data)}}}
        if gid:
            requests.patch(f'https://api.github.com/gists/{gid}', headers={'Authorization': 'token ' + tok}, json=gd)
        else:
            requests.post('https://api.github.com/gists', headers={'Authorization': 'token ' + tok}, json=gd)
    except: pass

def fetch_news(seen_titles):
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                t = entry.get('title', '')
                h = title_hash(t)
                if h not in seen_titles:
                    articles.append({'title': t, 'summary': entry.get('summary', '')[:300], 'hash': h})
        except: pass
    random.shuffle(articles)
    return articles[:25]

def generate_scripts(articles):
    txt = '\n'.join([f"{i+1}. {a['title']}: {a['summary']}" for i, a in enumerate(articles[:20])])
    prompt = f"""You are a viral YouTube Shorts script writer for a finance news channel.
Today's headlines:\n{txt}
Pick the {VIDEOS_PER_RUN} most engaging stories.
Write a YouTube Shorts script (max 150 words).
Rules:
- Hook MUST grab attention in FIRST 2 SECONDS
- Use "YOU", "YOUR money"
- End EXACTLY with: "Follow for daily finance news!"

Return ONLY valid JSON array:
[{{ "title":"emoji+title", "script":"full script", "tags":["finance", "news"], "search_query":"pexels keywords", "emoji":"📈" }}]"""

    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    models = ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant']

    for attempt in range(3):
        model = models[0] if attempt < 2 else models[1]
        try:
            payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.85})
            resp = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, data=payload, timeout=30)
            if resp.status_code == 200:
                text = resp.json()['choices'][0]['message']['content'].strip()
                if '```' in text:
                    text = text.split('```')[1] if len(text.split('```')) > 1 else text.split('```')[0]
                    if text.startswith('json'): text = text[4:]
                try:
                    parsed = json.loads(text.strip())
                    if isinstance(parsed, dict): parsed = [parsed]
                    if isinstance(parsed, list) and len(parsed) > 0: return parsed
                except: pass
        except: pass
        time.sleep(2)
    raise Exception('Groq failed after 3 attempts')

def clean_script_for_tts(script):
    script = re.sub(r'[\U00010000-\U0010ffff]', '', script, flags=re.UNICODE)
    script = re.sub(r'[*_#~|]', '', script)
    script = re.sub(r'http\S+', '', script).replace('#', '')
    return re.sub(r'\s+', ' ', script).strip()

async def generate_audio(script, output_path):
    voice, rate, pitch = VOICES[_voice_idx[0] % len(VOICES)]
    _voice_idx[0] += 1
    communicate = edge_tts.Communicate(script, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)

def _fetch_one_pexels_video(query, output_path, used_ids=None):
    headers = {'Authorization': PEXELS_API_KEY}
    used_ids = used_ids or set()
    for q in [query, 'business finance', 'stock market trading']:
        try:
            url = f'https://api.pexels.com/videos/search?query={q}&orientation=portrait&per_page=15&size=medium'
            resp = requests.get(url, headers=headers, timeout=15)
            videos = resp.json().get('videos', [])
            candidates = [v for v in videos if v.get('duration', 0) >= 10 and v['id'] not in used_ids]
            if candidates:
                video = random.choice(candidates[:5])
                files = sorted(video['video_files'], key=lambda x: x.get('width', 0), reverse=True)
                r = requests.get(files[0]['link'], stream=True, timeout=30)
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
                return video['id']
        except: continue
    raise Exception(f'Could not fetch Pexels video for: {query}')

def download_pexels_multi(query, tmpdir, count=3):
    paths, used_ids = [], set()
    base_queries = [query, random.choice(PEXELS_QUERIES), random.choice(PEXELS_QUERIES)]
    for i in range(count):
        q = base_queries[i % len(base_queries)]
        p = os.path.join(tmpdir, f'clip_{i}.mp4')
        try:
            vid_id = _fetch_one_pexels_video(q, p, used_ids)
            used_ids.add(vid_id)
            paths.append(p)
        except: pass
    if not paths: raise Exception('No Pexels clips downloaded!')
    return paths

def concat_videos(clip_paths, output_path, target_duration):
    if len(clip_paths) == 1:
        import shutil; shutil.copy(clip_paths[0], output_path); return
    list_file = output_path + '_list.txt'
    repeats = max(1, int(target_duration / (len(clip_paths) * 8)) + 1)
    with open(list_file, 'w') as f:
        for _ in range(repeats):
            for p in clip_paths: f.write(f"file '{p}'\n")
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
        '-vf', 'scale=1080:1920', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-t', str(target_duration), output_path
    ], check=True, capture_output=True)
    os.remove(list_file)

def create_text_image(text, font_path, font_size, max_width):
    image = Image.new("RGBA", (max_width, int(font_size * 2.5)), (0, 0, 0, 0))
    try: font = ImageFont.truetype(font_path, font_size)
    except: font = ImageFont.load_default()
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (max_width - text_w) / 2
    y = (font_size * 2.5 - text_h) / 2
    draw.text((x, y), text, font=font, fill="yellow", stroke_width=6, stroke_fill="black")
    return np.array(image)

def create_shorts_video_with_ai(video_path, audio_path, output_path, title):
    print("      -> Sesi Whisper ile analiz ediliyor...")
    loaded_audio = whisper.load_audio(audio_path)
    model = whisper.load_model("tiny.en", device="cpu")
    result = whisper.transcribe(model, loaded_audio, language="en")
    
    print("      -> MoviePy ile kelimeler videoya ekleniyor...")
    audio_clip = mp.AudioFileClip(audio_path)
    bg_clip = mp.VideoFileClip(video_path)
    
    bg_clip = bg_clip.subclip(0, audio_clip.duration)
    bg_clip = bg_clip.set_audio(audio_clip)

    text_clips = []
    safe_title = title.replace("'", "").replace('"', '')[:35].upper()
    title_array = create_text_image(f"FINANCE NEWS\n{safe_title}", FONT, 60, 1080)
    title_clip = mp.ImageClip(title_array).set_duration(audio_clip.duration).set_position(('center', 150))
    text_clips.append(title_clip)

    for segment in result['segments']:
        for word_info in segment['words']:
            start = word_info['start']
            end = word_info['end']
            text = word_info['text'].strip().upper()
            if end - start < 0.2: end = start + 0.2
            txt_array = create_text_image(text, FONT, 90, 1080)
            txt_clip = mp.ImageClip(txt_array).set_start(start).set_end(end).set_position(('center', 'center'))
            text_clips.append(txt_clip)

    final_clip = mp.CompositeVideoClip([bg_clip] + text_clips)
    final_clip.write_videofile(output_path, fps=30, codec="libx264", audio_codec="aac", preset="fast", threads=4, logger=None)
    
    bg_clip.close()
    audio_clip.close()
    final_clip.close()

def get_youtube_service():
    creds = Credentials(token=None, refresh_token=YOUTUBE_REFRESH_TOKEN, client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET, token_uri='https://oauth2.googleapis.com/token')
    creds.refresh(Request())
    return build('youtube', 'v3', credentials=creds)

def upload_to_youtube(youtube, video_path, title, tags):
    body = {
        'snippet': {'title': title[:100], 'description': f"{title}\n\nSubscribe for daily finance news! #Shorts #Finance", 'tags': tags[:30] + ['shorts', 'finance'], 'categoryId': '25'},
        'status': {'privacyStatus': 'public', 'madeForKids': False}
    }
    media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = None
    while response is None: status, response = request.next_chunk()
    return response['id']

async def main():
    print('Starting Upgraded YouTube Finance Shorts Bot...')
    seen_titles = load_seen_titles()
    articles = fetch_news(seen_titles)
    if not articles: return
    
    scripts = generate_scripts(articles)
    youtube = get_youtube_service()
    success = 0

    for i, item in enumerate(scripts):
        print(f'\n--- Video {i+1}/{len(scripts)}: {item.get("title", "Finance Shorts")} ---')
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path = os.path.join(tmpdir, 'audio.mp3')
                video_raw = os.path.join(tmpdir, 'raw.mp4')
                video_out = os.path.join(tmpdir, 'output.mp4')

                item['script'] = clean_script_for_tts(item.get('script', 'Welcome to finance news.'))
                
                print('  1. Ses Oluşturuluyor...')
                await generate_audio(item['script'], audio_path)

                print('  2. Pexels Videoları İndiriliyor...')
                video_clips = download_pexels_multi(item.get('search_query', 'finance'), tmpdir, count=3)
                concat_videos(video_clips, video_raw, 60)
                
                print('  3. Yapay Zeka Kurgu ve Altyazı Başlıyor...')
                create_shorts_video_with_ai(video_raw, audio_path, video_out, item.get('title', 'Finance News'))

                print('  4. YouTube\'a Yükleniyor...')
                
                # İŞTE BURASI HAYAT KURTARAN YER: '.get' ile hata almayı engelliyoruz!
                safe_tags = item.get('tags', ['finance', 'news', 'money'])
                
                upload_to_youtube(youtube, video_out, item.get('title', 'Finance News'), safe_tags)

                success += 1
                seen_titles.add(title_hash(item.get('title', '')))

        except Exception as e:
            print(f'  HATA: {e}')
            continue

    save_seen_titles(seen_titles)
    print(f'\nDone! {success} videolar başarıyla yüklendi.')

if __name__ == '__main__':
    asyncio.run(main())
