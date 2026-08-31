import os
import subprocess

def get_live_streams(youtube_url):
    """Uses yt-dlp to extract titles and m3u8 URLs for active live streams only."""
    try:
        # Optimized yt-dlp command
        cmd = [
            "yt-dlp",
            "--print", "%(title)s|||%(url)s",
            "--match-filter", "live_status = 'is_live'", # STRICTLY check for active live streams
            "--playlist-end", "2",                      # Limit to max 2 concurrent streams to save time
            "--no-playlist" if not "/@ " in youtube_url else "--flat-playlist",
            youtube_url
        ]
        
        # Run with a 30-second timeout per channel so it never hangs forever
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        
        streams = []
        lines = result.stdout.strip().split('\n')
        for line in lines:
            if "|||" in line:
                title, m3u8_url = line.split("|||", 1)
                # Ensure we actually extracted a valid stream link
                if m3u8_url.strip().endswith('.m3u8') or 'manifest' in m3u8_url:
                    streams.append({"title": title.strip(), "url": m3u8_url.strip()})
        return streams
    except subprocess.TimeoutExpired:
        print(f"Timeout: {youtube_url} took too long to respond.")
        return []
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
        print(f"Checking live status for: {url}")
        streams = get_live_streams(url)
        
        if not streams:
            print(f"--> No active live stream found for {url}")
            continue
            
        for index, stream in enumerate(streams):
            title = stream["title"]
            m3u8_url = stream["url"]
            
            # If a channel has 2 live streams running simultaneously, name them safely
            stream_name = f"{title} (Live {index + 1})" if len(streams) > 1 else title
            
            playlist_content.append(f'#EXTINF:-1 tvg-name="{stream_name}" group-title="News", {stream_name}\n')
            playlist_content.append(f"{m3u8_url}\n")

    with open("live_news.m3u", "w", encoding="utf-8") as out_file:
        out_file.writelines(playlist_content)
    
    print("\nSuccessfully updated live_news.m3u with active links!")

if __name__ == "__main__":
    main()
