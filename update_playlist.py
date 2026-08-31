import os
import subprocess

def get_live_streams(channel_url):
    """Resolves a channel /live URL to its active video, then extracts the raw m3u8 link."""
    try:
        # Step 1: Get the real active video URL from the channel page
        video_url_cmd = [
            "yt-dlp",
            "--print", "webpage_url",
            "--match-filter", "live_status = 'is_live'",
            channel_url
        ]
        video_url_result = subprocess.run(video_url_cmd, capture_output=True, text=True, timeout=15)
        
        real_video_url = video_url_result.stdout.strip()
        
        # If no active video URL is found or returned, the channel is completely offline
        if not real_video_url or "watch?v=" not in real_video_url:
            print(f"--> No active live video link found for: {channel_url}")
            return []

        print(f"    Found active video: {real_video_url}")

        # Step 2: Extract the raw streaming m3u8 URL from the resolved video link
        m3u8_cmd = [
            "yt-dlp",
            "-g", 
            real_video_url
        ]
        m3u8_result = subprocess.run(m3u8_cmd, capture_output=True, text=True, timeout=15)
        m3u8_url = m3u8_result.stdout.strip()

        if m3u8_url and ('m3u8' in m3u8_url or 'manifest' in m3u8_url):
            # Step 3: Get a clean title of the live stream
            title_cmd = ["yt-dlp", "--get-title", real_video_url]
            title_result = subprocess.run(title_cmd, capture_output=True, text=True, timeout=10)
            stream_title = title_result.stdout.strip() if title_result.returncode == 0 else "Live News Stream"
            
            return [{"title": stream_title, "url": m3u8_url}]
            
        return []
    except Exception as e:
        print(f"Skipping {channel_url} due to parsing error.")
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
            
            playlist_content.append(f'#EXTINF:-1 tvg-name="{title}" group-title="News", {title}\n')
            playlist_content.append(f"{m3u8_url}\n")

    with open("live_news.m3u", "w", encoding="utf-8") as out_file:
        out_file.writelines(playlist_content)
    
    print("\nSuccess! live_news.m3u has been populated with active streams.")

if __name__ == "__main__":
    main()
