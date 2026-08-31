import os
import subprocess
import re

def get_live_streams(channel_url):
    """Bypasses YouTube bot blocks by converting handle URLs to direct data endpoints."""
    try:
        # Extract the username handle from the URL (e.g., @ArynewsTvofficial)
        match = re.search(r"(@[A-Za-z0-9_\-\.]+)", channel_url)
        if not match:
            print(f"Skipping malformed URL: {channel_url}")
            return []
        
        handle = match.group(1)
        # Direct unblocked endpoint forcing YouTube to serve the true live video container
        direct_feed = f"https://www.youtube.com/{handle}/live"

        print(f"--> Extracting feed for {handle}")

        # yt-dlp flags configured to impersonate a standard Safari browser and extract the live manifest directly
        cmd = [
            "yt-dlp",
            "-g",                            # Directly fetch stream URL
            "--user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "--print", "%(title)s|||%(url)s", # Return title and stream URL together
            "--no-warnings",
            direct_feed
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        output = result.stdout.strip()

        if output and "|||" in output:
            title, m3u8_url = output.split("|||", 1)
            if "m3u8" in m3u8_url or "manifest" in m3u8_url:
                print(f"    [SUCCESS] Found live link for {handle}")
                return [{"title": title.strip(), "url": m3u8_url.strip()}]
        
        print(f"    [OFFLINE or BLOCKED] No active streams found for {handle}")
        return []
    except Exception as e:
        print(f"Error checking {channel_url}: {e}")
        return []

def main():
    if not os.path.exists("channels.txt"):
        print("Error: channels.txt not found.")
        return

    playlist_content = ["#EXTM3U\n"]

    with open("channels.txt", "r") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    for url in urls:
        streams = get_live_streams(url)
        
        for stream in streams:
            title = stream["title"]
            m3u8_url = stream["url"]
            
            playlist_content.append(f'#EXTINF:-1 tvg-name="{title}" group-title="News", {title}\n')
            playlist_content.append(f"{m3u8_url}\n")

    with open("live_news.m3u", "w", encoding="utf-8") as out_file:
        out_file.writelines(playlist_content)
    
    print("\nProcess finished. File write sequence executed.")

if __name__ == "__main__":
    main()
