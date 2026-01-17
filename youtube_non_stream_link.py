import xml.etree.ElementTree as ET
import logging
import re
import requests

# ------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

INPUT_XML = "youtubelinks.xml"
OUTPUT_M3U = "youtube_output.m3u"


# ------------------------------------------------------------
# XML parsing
# ------------------------------------------------------------
def parse_xml(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    channels = []
    for ch in root.findall("channel"):
        channels.append({
            "name": ch.findtext("channel-name", "").strip(),
            "tvg-id": ch.findtext("tvg-id", "").strip(),
            "tvg-name": ch.findtext("tvg-name", "").strip(),
            "tvg-logo": ch.findtext("tvg-logo", "").strip(),
            "group-title": ch.findtext("group-title", "General").strip(),
            "youtube-url": ch.findtext("youtube-url", "").strip(),
        })

    return channels


# ------------------------------------------------------------
# Extract watch URL from @channel/live
# ------------------------------------------------------------
def extract_watch_url_from_live_page(html):
    # canonical watch link
    match = re.search(
        r'https://www\.youtube\.com/watch\?v=[a-zA-Z0-9_-]{11}',
        html
    )
    if match:
        return match.group(0)

    # JSON encoded
    match = re.search(
        r'"url"\s*:\s*"(https:\\/\\/www\.youtube\.com\\/watch\\?v=[^"]+)"',
        html
    )
    if match:
        return match.group(1).replace("\\/", "/")

    return None


# ------------------------------------------------------------
# Extract video ID
# ------------------------------------------------------------
def get_video_id(session, url):
    logging.info(f"Navigating to: {url}")
    r = session.get(url, timeout=20)
    html = r.text

    # ✅ Handle @channel/live by redirecting to watch URL
    if "/@" in url and url.rstrip("/").endswith("/live"):
        watch_url = extract_watch_url_from_live_page(html)
        if not watch_url:
            logging.warning("Failed to resolve live watch URL")
            return None

        logging.info(f"Redirecting to live watch URL: {watch_url}")
        return get_video_id(session, watch_url)

    # Normal watch page
    match = re.search(
        r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"',
        html
    )
    return match.group(1) if match else None


# ------------------------------------------------------------
# Extract HLS stream
# ------------------------------------------------------------
def extract_youtube_stream(youtube_url):
    session = requests.Session()

    video_id = get_video_id(session, youtube_url)
    if not video_id:
        logging.warning("No video ID found")
        return None

    logging.info(f"Using video ID: {video_id}")

    watch = session.get(f"https://www.youtube.com/watch?v={video_id}", timeout=20)
    page = watch.text

    api_key = re.search(
        r'["\']INNERTUBE_API_KEY["\']\s*:\s*["\']([^"\']+)["\']',
        page
    )
    visitor = re.search(
        r'["\']visitorData["\']\s*:\s*["\']([^"\']+)["\']',
        page
    )

    if not api_key or not visitor:
        logging.error("Failed to extract InnerTube tokens")
        return None

    player_url = f"https://www.youtube.com/youtubei/v1/player?key={api_key.group(1)}"

    payload = {
        "context": {
            "client": {
                "clientName": "IOS",
                "clientVersion": "19.45.4",
                "visitorData": visitor.group(1)
            }
        },
        "videoId": video_id
    }

    r = session.post(player_url, json=payload, timeout=20)
    data = r.json()

    hls = data.get("streamingData", {}).get("hlsManifestUrl")
    if hls:
        logging.info("HLS retrieved successfully")
        return hls

    logging.warning("No HLS stream found")
    return None


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
def main():
    channels = parse_xml(INPUT_XML)

    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for ch in channels:
            logging.info(f"--- Processing: {ch['name']} ---")

            hls = extract_youtube_stream(ch["youtube-url"])
            if not hls:
                logging.warning(f"Failed to find stream for {ch['name']}")
                continue

            f.write(
                f'#EXTINF:-1 tvg-id="{ch["tvg-id"]}" '
                f'tvg-name="{ch["tvg-name"]}" '
                f'tvg-logo="{ch["tvg-logo"]}" '
                f'group-title="{ch["group-title"]}",'
                f'{ch["name"]}\n'
            )
            f.write(f"{hls}\n")

            logging.info(f"Successfully exported {ch['name']}")

    logging.info(f"Playlist saved: {OUTPUT_M3U}")


if __name__ == "__main__":
    main()
