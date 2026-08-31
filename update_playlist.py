import os
import subprocess

def get_live_streams(youtube_url):
    """Uses yt-dlp to directly grab the true m3u8 live manifest stream URL."""
    try:
        # Fixed yt-dlp flags to extract the direct streaming manifest link instantly
        cmd = [
            "yt-dlp",
            "-g",                            # Tell yt-dlp to output the raw URL directly
            "--match-filter", "live_status = 'is_live'", # Force it to drop expired/ended sessions
            youtube_url
        ]
        
        # Give each channel up to 20 seconds to process
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=20)
        
        m3u8_url = result.stdout.strip()
        
        # Verify that we extracted a valid HLS link
        if m3u8_url and ('m3u8' in m3u8_url or 'manifest' in m3u8_url):
            # Extract a clean title for display
            title_cmd = ["yt-dlp", "--get-title", youtube_url]
            title_result = subprocess.run(title_cmd, capture_output=True, text=True, timeout=10)
            stream_title = title_result.stdout.strip() if title_result.returncode == 0 else "Live News Stream"
            
            return [{"title": stream_title, "url": m3u8_url}]
        return []
    except Exception as e:
        print(f"Skipping {youtube_url}: Channel is currently offline.")
        return []

def main():
    if not os.path.exists("channels.txt"):
        print("Error: channels.txt not found.")
        return

    playlist_content = ["#EXTM3U\n"]

    with open("channels.txt", "r") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    for url in urls:
        print(f"Checking live stream for: {url}")
        streams = get_live_streams(url)
        
        if not streams:
            continue
            
        for stream in streams:
            title = stream["title"]
            m3u8_url = stream["url"]
            
            # Write a perfectly formatted, single-line M3U entry for IPTV apps
            playlist_content.append(f'#EXTINF:-1 tvg-name="{title}" group-title="News", {title}\n')
            playlist_content.append(f"{m3u8_url}\n")

    with open("live_news.m3u", "w", encoding="utf-8") as out_file:
        out_file.writelines(playlist_content)
    
    print("\nSuccess! live_news.m3u has been populated with active streams.")

if __name__ == "__main__":
    main()
