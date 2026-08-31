import os
import subprocess
import re
import urllib.request

def get_live_video_url(channel_url):
    """Fetches the channel's live page via raw HTML to grab the active video ID."""
    try:
        # Match the channel handle
        match = re.search(r"(@[A-Za-z0-9_\-\.]+)", channel_url)
        if not match:
            return None
        
        handle = match.group(1)
        url = f"https://youtube.com{handle}/live"
        
        # Request headers to look like a standard desktop browser
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        
        # Read the raw webpage HTML content
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8')
            
        # Look for the canonical watch URL embedded inside YouTube's metadata
        video_match = re.search(r'href="https://youtube.comwatch\?v=([^"]+)"', html)
        if video_match:
            video_id = video_match.group(1)
            return f"https://youtube.comwatch?v={video_id}"
            
        # Fallback regex pattern for internal video formats
        video_match_alt = re.search(r'"videoId":"([^"]+)"', html)
        if video_match_alt:
            video_id = video_match_alt.group(1)
            # Make sure it's not a generic template placeholder ID
            if len(video_id) == 11:
                return f"https://youtube.comwatch?v={video_id}"
                
        return None
    except Exception as e:
        print(f"    [X] HTML fetch failed for {channel_url}: {e}")
        return None

def get_m3u8_link(video_url):
    """Passes the direct video URL to yt-dlp to grab the direct stream link."""
    try:
        cmd = [
            "yt-dlp",
            "-g", 
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            video_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        m3u8_url = result.stdout.strip()
        
        if m3u8_url and ('m3u8' in m3u8_url or 'manifest' in m3u8_url):
            return m3u8_url
        return None
    except Exception:
        return None

def main():
    if not os.path.exists("channels.txt"):
        print("[!] Error: channels.txt not found.")
        return

    playlist_content = ["#EXTM3U\n"]

    with open("channels.txt", "r") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"Processing {len(urls)} total channels...")

    for url in urls:
        print(f"\n--> Fetching Live ID for: {url}")
        video_url = get_live_video_url(url)
        
        if not video_url:
            print(f"    [-] Channel is offline or live broadcast is not found.")
            continue
            
        print(f"    [✓] Found Live Video ID: {video_url}")
        print(f"    --> Extracting direct m3u8 stream...")
        
        m3u8_url = get_m3u8_link(video_url)
        if m3u8_url:
            # We use the handle name as the title placeholder to keep it fast
            handle = re.search(r"(@[A-Za-z0-9_\-\.]+)", url).group(1).replace('@', '')
            playlist_content.append(f'#EXTINF:-1 tvg-name="{handle}" group-title="Live News", {handle.upper()}\n')
            playlist_content.append(f"{m3u8_url}\n")
            print(f"    [✓] Stream added to playlist!")
        else:
            print(f"    [X] Failed to extract stream links via yt-dlp.")

    # Prevent writing a completely empty playlist over your data
    if len(playlist_content) <= 1:
        print("\n[!] Scraper returned 0 active streams. Keeping old file intact.")
        return

    with open("live_news.m3u", "w", encoding="utf-8") as out_file:
        out_file.writelines(playlist_content)
    
    print(f"\n[✓] Finished successfully! File generated with active links.")

if __name__ == "__main__":
    main()
