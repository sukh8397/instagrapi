#!/usr/bin/env python3
"""
Live Web Application & REST API for Instagram Photo & Media Scraper.
Multi-engine extraction pipeline combining Instaloader, Instagrapi, and yt-dlp.
"""

import os
import io
import json
import zipfile
import re
import time
from urllib.parse import urlparse
from flask import Flask, request, jsonify, render_template, send_file, Response
import requests

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.urandom(24).hex()

LATEST_RESULTS = []


def parse_query(raw_query: str):
    """
    Determine if query is an Instagram post/reel shortcode or a profile username.
    Returns (query_type, identifier) where query_type is 'post' or 'user'.
    """
    q = raw_query.strip()
    
    # Check post / reel / tv shortcode
    post_match = re.search(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", q)
    if post_match:
        return "post", post_match.group(1)

    # Check raw shortcode (10-12 chars alphanumeric with _ -)
    if re.match(r"^[A-Za-z0-9_-]{10,12}$", q):
        return "post", q

    # Check profile URL
    if "instagram.com" in q:
        parsed = urlparse(q)
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0] not in ["p", "reel", "reels", "tv", "stories", "explore"]:
            return "user", parts[0]

    # Plain username (e.g. @natgeo or natgeo)
    clean_user = q.lstrip("@").strip()
    if re.match(r"^[A-Za-z0-9._]{1,30}$", clean_user):
        return "user", clean_user

    return "unknown", q


def scrape_post_pipeline(shortcode: str, session_id: str = None):
    """Scrape a post using Instaloader with fallbacks."""
    # Method 1: Instaloader
    try:
        import instaloader
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            quiet=True,
        )
        if session_id:
            L.context._session.cookies.set("sessionid", session_id, domain=".instagram.com")

        post = instaloader.Post.from_shortcode(L.context, shortcode)
        media_urls = []
        media_type = "IMAGE"

        if post.typename == "GraphSidecar":
            media_type = "CAROUSEL"
            for node in post.get_sidecar_nodes():
                if not node.is_video and node.display_url:
                    media_urls.append(node.display_url)
        else:
            if not post.is_video and post.url:
                media_urls.append(post.url)
            elif post.is_video and post.url:
                media_type = "VIDEO"
                media_urls.append(post.url)

        if media_urls:
            caption = post.caption or ""
            return [{
                "url": f"https://www.instagram.com/p/{shortcode}/",
                "shortcode": shortcode,
                "username": post.owner_username,
                "full_name": getattr(post.owner_profile, "full_name", post.owner_username),
                "title": caption.split("\n")[0][:100] if caption else f"Post by @{post.owner_username}",
                "caption": caption,
                "timestamp": post.date_utc.isoformat() if post.date_utc else "",
                "likes": post.likes or 0,
                "comments_count": post.comments or 0,
                "media_type": media_type,
                "media_urls": media_urls,
                "thumbnail_url": post.url or media_urls[0],
                "downloaded_files": []
            }]
    except Exception as e:
        print(f"[Instaloader Post error] {e}")

    # Method 2: yt-dlp fallback
    try:
        import yt_dlp
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.instagram.com/p/{shortcode}/", download=False)
            if info:
                media_urls = []
                entries = info.get("entries")
                if entries:
                    for e in entries:
                        u = e.get("url") or e.get("thumbnail")
                        if u:
                            media_urls.append(u)
                else:
                    u = info.get("url") or info.get("thumbnail")
                    if u:
                        media_urls.append(u)

                if media_urls:
                    caption = info.get("description") or ""
                    return [{
                        "url": f"https://www.instagram.com/p/{shortcode}/",
                        "shortcode": shortcode,
                        "username": info.get("uploader") or "",
                        "full_name": info.get("uploader") or "",
                        "title": info.get("title") or (caption.split("\n")[0][:100] if caption else f"Post {shortcode}"),
                        "caption": caption,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(info["timestamp"])) if info.get("timestamp") else "",
                        "likes": info.get("like_count") or 0,
                        "comments_count": info.get("comment_count") or 0,
                        "media_type": "CAROUSEL" if len(media_urls) > 1 else "IMAGE",
                        "media_urls": media_urls,
                        "thumbnail_url": info.get("thumbnail") or media_urls[0],
                        "downloaded_files": []
                    }]
    except Exception as e:
        print(f"[yt-dlp Post error] {e}")

    return None


def scrape_profile_pipeline(username: str, max_posts: int = 10, session_id: str = None):
    """Scrape a profile using Instaloader with private-account awareness."""
    results = []
    try:
        import instaloader
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            quiet=True,
        )
        if session_id:
            L.context._session.cookies.set("sessionid", session_id, domain=".instagram.com")

        profile = instaloader.Profile.from_username(L.context, username)
        profile_info = {
            "username": profile.username,
            "full_name": profile.full_name,
            "biography": profile.biography,
            "followers": profile.followers,
            "is_private": profile.is_private,
            "profile_pic_url": profile.profile_pic_url,
            "mediacount": profile.mediacount,
        }

        # Profile avatar
        if profile.profile_pic_url:
            results.append({
                "url": f"https://www.instagram.com/{username}/",
                "username": profile.username,
                "full_name": profile.full_name,
                "title": f"@{username} Profile Picture",
                "caption": profile.biography or (f"Private account with {profile.followers:,} followers" if profile.is_private else ""),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "likes": 0,
                "comments_count": 0,
                "media_type": "PROFILE_PIC",
                "media_urls": [profile.profile_pic_url],
                "thumbnail_url": profile.profile_pic_url,
                "profile_info": profile_info,
                "downloaded_files": []
            })

        # Fetch posts if public or session cookie provided
        if not profile.is_private or session_id:
            count = 0
            for post in profile.get_posts():
                if count >= max_posts:
                    break
                media_urls = []
                if post.typename == "GraphSidecar":
                    for node in post.get_sidecar_nodes():
                        if not node.is_video and node.display_url:
                            media_urls.append(node.display_url)
                else:
                    if not post.is_video and post.url:
                        media_urls.append(post.url)
                    elif post.is_video and post.url:
                        media_urls.append(post.url)

                if media_urls:
                    caption = post.caption or ""
                    results.append({
                        "url": f"https://www.instagram.com/p/{post.shortcode}/",
                        "shortcode": post.shortcode,
                        "username": profile.username,
                        "full_name": profile.full_name,
                        "title": caption.split("\n")[0][:100] if caption else f"Post by @{profile.username}",
                        "caption": caption,
                        "timestamp": post.date_utc.isoformat() if post.date_utc else "",
                        "likes": post.likes or 0,
                        "comments_count": post.comments or 0,
                        "media_type": "CAROUSEL" if len(media_urls) > 1 else "IMAGE",
                        "media_urls": media_urls,
                        "thumbnail_url": post.url or media_urls[0],
                        "profile_info": profile_info,
                        "downloaded_files": []
                    })
                    count += 1

        return results, profile_info
    except Exception as e:
        print(f"[Profile scrape error] {e}")
        return results, {"error": str(e)}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "Scrape Instagram Photos Web API",
        "version": "3.0.0"
    })


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    global LATEST_RESULTS
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"success": False, "error": "Query (URL or username) is required."}), 400

    session_id = data.get("session_id", "").strip() or os.environ.get("INSTAGRAM_SESSION_ID")
    max_posts = int(data.get("max_posts", 10))

    q_type, identifier = parse_query(query)

    if q_type == "post":
        results = scrape_post_pipeline(identifier, session_id=session_id)
        if not results:
            return jsonify({
                "success": False,
                "error": f"Could not load Instagram post [{identifier}]. Instagram may require authentication. Try providing your sessionid cookie in Advanced Settings."
            }), 404

        LATEST_RESULTS = results
        total_photos = sum(len(r.get("media_urls", [])) for r in results)
        return jsonify({
            "success": True,
            "query": query,
            "posts_count": len(results),
            "total_photos": total_photos,
            "results": results
        })

    elif q_type == "user":
        results, profile_info = scrape_profile_pipeline(identifier, max_posts=max_posts, session_id=session_id)
        
        if not results:
            err_msg = profile_info.get("error", "")
            if "Login required" in err_msg or profile_info.get("is_private"):
                return jsonify({
                    "success": False,
                    "error": f"@{identifier} is a Private Account. Instagram requires you to be logged in and following them to view their posts. Please provide your Instagram sessionid cookie in Advanced Settings."
                }), 403
            return jsonify({
                "success": False,
                "error": f"Could not find profile @{identifier}. Please verify the username."
            }), 404

        LATEST_RESULTS = results
        total_photos = sum(len(r.get("media_urls", [])) for r in results)
        is_priv = profile_info.get("is_private", False)

        resp_payload = {
            "success": True,
            "query": query,
            "posts_count": len(results),
            "total_photos": total_photos,
            "results": results
        }
        if is_priv and not session_id:
            resp_payload["notice"] = f"Note: @{identifier} is a private account. Showing profile picture. To view all private posts, paste your Instagram sessionid in Advanced Settings."

        return jsonify(resp_payload)

    else:
        return jsonify({
            "success": False,
            "error": "Unrecognized query format. Please enter an Instagram post URL (e.g. https://www.instagram.com/p/...) or profile username (e.g. @natgeo)."
        }), 400


@app.route("/api/download-zip", methods=["GET"])
def download_zip():
    global LATEST_RESULTS
    if not LATEST_RESULTS:
        return jsonify({"error": "No recent scrape results available."}), 400

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps(LATEST_RESULTS, ensure_ascii=False, indent=2))
        
        count = 0
        for res in LATEST_RESULTS:
            user = res.get("username", "instagram")
            code = res.get("shortcode", f"media_{count}")
            for idx, u in enumerate(res.get("media_urls", [])):
                try:
                    r = requests.get(u, timeout=15)
                    if r.status_code == 200:
                        arcname = f"{user}_{code}_{idx+1}.jpg"
                        zf.writestr(arcname, r.content)
                        count += 1
                except Exception:
                    pass

    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype="application/zip",
        as_attachment=True,
        download_name="instagram_photos.zip"
    )


@app.route("/api/export/json", methods=["GET"])
def export_json():
    global LATEST_RESULTS
    if not LATEST_RESULTS:
        return jsonify({"error": "No results available."}), 400

    return Response(
        json.dumps(LATEST_RESULTS, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=instagram_scrape.json"}
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
