"""
fetch_discord.py – Read messages from a Discord channel via Bot REST API.
Saves to data/mr_discord.json.

No discord.py – only stdlib urllib.request.
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

DISCORD_API = "https://discord.com/api/v10"


def _api_get(path: str, token: str) -> dict | list | None:
    """Make a GET request to Discord API. Returns parsed JSON or None on error."""
    url = f"{DISCORD_API}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "MarketReportBot (portfolio-tracker, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"  [WARN] Discord API {path} → HTTP {exc.code}: {exc.reason}")
        return None
    except Exception as exc:
        print(f"  [WARN] Discord API {path} → {exc}")
        return None


def snowflake_from_timestamp(ts: float) -> int:
    """Convert Unix timestamp to Discord snowflake."""
    discord_epoch = 1420070400000  # 2015-01-01 UTC in ms
    ms = int(ts * 1000)
    return (ms - discord_epoch) << 22


def format_message(msg: dict) -> dict:
    """Transform a raw Discord message into our output format."""
    # Parse timestamp
    ts_raw = msg.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        date_str = ""

    author_data = msg.get("author", {})
    author = author_data.get("global_name") or author_data.get("username", "Unknown")

    embeds_raw = msg.get("embeds", [])
    embeds = []
    for emb in embeds_raw:
        embeds.append({
            "title": emb.get("title", ""),
            "url": emb.get("url", ""),
            "description": (emb.get("description", "") or "")[:500],
        })

    return {
        "content": (msg.get("content", "") or "")[:2000],
        "author": author,
        "date": date_str,
        "embeds": embeds,
    }


def main():
    os.makedirs("data", exist_ok=True)

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    guild_name = os.environ.get("DISCORD_GUILD_NAME", "as club")
    channel_name = os.environ.get("DISCORD_CHANNEL_NAME", "as-news")

    if not token:
        print("[WARN] DISCORD_BOT_TOKEN not set – saving empty message list.")
        with open(os.path.join("data", "mr_discord.json"), "w") as f:
            json.dump([], f)
        return

    # ── Find guild by name ────────────────────────────────────────────────────
    print(f"Looking for guild '{guild_name}'...")
    guilds = _api_get("/users/@me/guilds", token)
    if not guilds:
        print("[WARN] Could not retrieve guilds – saving empty list.")
        with open(os.path.join("data", "mr_discord.json"), "w") as f:
            json.dump([], f)
        return

    guild_id = None
    for g in guilds:
        if g.get("name", "").lower() == guild_name.lower():
            guild_id = g["id"]
            break

    if not guild_id:
        print(f"[WARN] Guild '{guild_name}' not found. Available: {[g['name'] for g in guilds]}")
        with open(os.path.join("data", "mr_discord.json"), "w") as f:
            json.dump([], f)
        return

    print(f"Found guild id: {guild_id}")

    # ── Find channel by name ──────────────────────────────────────────────────
    channels = _api_get(f"/guilds/{guild_id}/channels", token)
    if not channels:
        print("[WARN] Could not retrieve channels – saving empty list.")
        with open(os.path.join("data", "mr_discord.json"), "w") as f:
            json.dump([], f)
        return

    channel_id = None
    for ch in channels:
        if ch.get("name", "").lower() == channel_name.lower():
            channel_id = ch["id"]
            break

    if not channel_id:
        available = [ch["name"] for ch in channels if ch.get("type") == 0]
        print(f"[WARN] Channel '{channel_name}' not found. Text channels: {available}")
        with open(os.path.join("data", "mr_discord.json"), "w") as f:
            json.dump([], f)
        return

    print(f"Found channel id: {channel_id}")

    # ── Paginate messages from last 7 days ────────────────────────────────────
    cutoff_snowflake = snowflake_from_timestamp(time.time() - 7 * 86400)
    after = str(cutoff_snowflake)
    all_messages = []
    page = 0

    while True:
        page += 1
        path = f"/channels/{channel_id}/messages?limit=100&after={after}"
        print(f"  Fetching page {page} (after={after})...")
        batch = _api_get(path, token)

        if not batch:
            break

        # Discord returns newest first when using 'after' – sort ascending
        batch_sorted = sorted(batch, key=lambda m: m["id"])
        all_messages.extend(batch_sorted)
        print(f"    → {len(batch_sorted)} messages")

        if len(batch) < 100:
            break  # Last page

        # Set 'after' to the last (newest) message id in this batch
        after = batch_sorted[-1]["id"]
        time.sleep(0.5)

    print(f"Total messages fetched: {len(all_messages)}")

    # Format and save
    formatted = [format_message(m) for m in all_messages]
    # Filter empty messages
    formatted = [m for m in formatted if m["content"].strip() or m["embeds"]]

    out_path = os.path.join("data", "mr_discord.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(formatted)} messages to {out_path}")


if __name__ == "__main__":
    main()
