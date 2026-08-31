import os
import subprocess
import json

def get_live_streams(youtube_url):
    """Uses yt-dlp to extract titles and m3u8 URLs for all active live streams."""
    try:
        # Request stream URLs and details in JSON format
        cmd = [
            "yt-dlp",
            "--print", "%(title)s|||%(url)s",
            "--flat-playlist",  # Handles channels with multiple concurrent live videos
            youtube_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        streams = []
        lines = result.stdout.strip().split('\n')
        for line in lines:
            if "|||" in line:
                title, m3u8_url = line.split("|||", 1)
                if m3u8_url.strip().endswith('.m3u8') or 'manifest' in m3u8_url:
                    streams.append({"title": title.strip(), "url": m3u8_url.strip()})
        return streams
    except Exception as e:
        print(f"Skipping {youtube_url} due to error: {e}")
        return []

def main():
    if not os.path.exists("channels.txt"):
        print("Error: channels.txt not found.")
        return

    playlist_content = ["#EXTM3U\n"]

    with open("channels.txt", "r") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    for url in urls:
        print(f"Fetching streams for: {url}")
        streams = get_live_streams(url)
        
        if not streams:
            continue
            
        for index, stream in enumerate(streams):
            title = stream["title"]
            m3u8_url = stream["url"]
            
            # If a channel has multiple live streams, index them so they have distinct names
            stream_name = f"{title} (Live {index + 1})" if len(streams) > 1 else title
            
            # Standard M3U formatting compatible with TVs and IPTV players
            playlist_content.append(f'#EXTINF:-1 tvg-name="{stream_name}" group-title="News", {stream_name}\n')
            playlist_content.append(f"{m3u8_url}\n")

    # Write out the combined playlist file
    with open("live_news.m3u", "w", encoding="utf-8") as out_file:
        out_file.writelines(playlist_content)
    
    print("Successfully generated live_news.m3u")

if __name__ == "__main__":
    main()
