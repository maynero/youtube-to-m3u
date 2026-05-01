# youtube-to-m3u

Play YouTube live streams and other Streamlink-supported live streams through an M3U playlist.

This project runs a small Flask/Waitress server on port `6095`. Your IPTV player calls the server's `/stream` endpoint with a source URL, and the server pipes the live stream back as MPEG-TS.

## Important note

Generated stream URLs are usually tied to the public IP address that requested them. Clients should normally be on the same network/public IP as the server running this project.

If your player is on a different network, run this near the player or put the generated M3U behind a restreaming proxy such as Threadfin.

## Run locally

```bash
python3 -m venv .venv_ytm3u
source .venv_ytm3u/bin/activate
pip install -r requirements.txt
python3 streamlink-m3u.py
```

The server listens on `0.0.0.0:6095`.

## Run with Docker

```bash
docker run -p 6095:6095 --name ytm3u -d ghcr.io/maynero/youtube-to-m3u:latest
```

## M3U playlist usage

Open `youtubelive.m3u` and replace `192.168.1.123` with the IP address or hostname of the machine running this server.

Example:

```m3u
#EXTM3U
#EXTINF:-1 tvg-name="ABC News" tvg-id="ABCNEWS.us" tvg-logo="https://github.com/tv-logo/tv-logos/blob/main/countries/united-states/abc-news-light-us.png?raw=true" group-title="News",ABC News
#KODIPROP:mimetype=video/mp2t
#KODIPROP:inputstream=inputstream.ffmpegdirect
http://192.168.1.123:6095/stream?url=https://www.youtube.com/@abcnews/live
```

You can change `tvg-name`, `tvg-id`, `tvg-logo`, `group-title`, and the channel display name to match your playlist and EPG. <br />
The `KODIPROP` is optional even for KODI, only use it if streams are not playing in KODI.

The script must stay running while clients play streams.

## Stream endpoint

```text
http://SERVER_IP:6095/stream?url=SOURCE_URL
```

Query parameters:

- `url`: Required. The YouTube, `youtu.be`, or Streamlink-supported source URL.
- `quality`: Optional. For YouTube, use a height such as `720` or a yt-dlp format id. For other sources, use a Streamlink quality such as `best`, `720p`, or `worst`. Non-YouTube streams default to `best`.
- `decryption_key`: Optional. Passed to Streamlink for encrypted streams.

Examples:

```text
http://192.168.1.123:6095/stream?url=https://www.youtube.com/@abcnews/live
http://192.168.1.123:6095/stream?url=https://www.youtube.com/@abcnews/live&quality=720
http://192.168.1.123:6095/stream?url=https://example.com/live.m3u8&quality=best
```

For channels with more than one live stream, a direct YouTube `/watch?...` URL can be used, but it may change when the broadcast stops and restarts.

## Process manager

Open the server root or `/processes` in a browser:

```text
http://SERVER_IP:6095/
http://SERVER_IP:6095/processes
```

The process manager shows active stream processes, connected clients, start times, and controls to kill one process or all running processes.

## Logging options

These environment variables control Streamlink logging:

- `STREAMLINK_LOG_ENABLED`: Set to `false` to disable Streamlink logfile output. Defaults to `true`.
- `STREAMLINK_LOG_LEVEL`: Streamlink log level. Defaults to `info`.
- `STREAMLINK_LOG_FILE`: Log file path. Defaults to `/tmp/streamlink.log`.

Docker example:

```bash
docker run -p 6095:6095 \
  -e STREAMLINK_LOG_ENABLED=false \
  --name ytm3u \
  -d ghcr.io/maynero/youtube-to-m3u:latest
```
