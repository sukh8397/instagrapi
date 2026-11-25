#!/usr/bin/env python3
"""
Live Web Application & REST API for instagrapi - Instagram Photo & Media Scraper
"""

import os
import io
import json
import zipfile
import re
from flask import Flask, request, jsonify, render_template, send_file, Response
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.urandom(24).hex()

LATEST_RESULTS = []


def get_client(session_id=None):
    cl = Client()
    cl.delay_range = [1, 2]
    # Check session cookie from request or environment
    sid = session_id or os.environ.get("INSTAGRAM_SESSION_ID")
    if sid:
        try:
            cl.login_by_sessionid(sid)
        except Exception:
            pass
    return cl


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "Instagrapi Web Service",
        "version": "3.2.20"
    })


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    global LATEST_RESULTS
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"success": False, "error": "Query (URL or username) is required."}), 400

    session_id = data.get("session_id", "").strip() or None
    max_posts = int(data.get("max_posts", 10))

    cl = get_client(session_id=session_id)
    results = []

    # Check if query is post URL
    shortcode_match = re.search(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", query)
    
    if shortcode_match or query.startswith("http"):
        try:
            pk = cl.media_pk_from_url(query)
            media = cl.media_info(pk)
            
            media_urls = []
            if media.media_type == 8 and media.resources:  # Carousel
                for res in media.resources:
                    target = res.thumbnail_url or (res.video_url if res.media_type == 2 else None)
                    if target:
                        media_urls.append(str(target))
            else:
                target = media.thumbnail_url or (media.video_url if media.media_type == 2 else None)
                if target:
                    media_urls.append(str(target))

            item = {
                "url": f"https://www.instagram.com/p/{media.code}/",
                "shortcode": media.code,
                "username": media.user.username,
                "full_name": media.user.full_name,
                "title": (media.caption_text or "").split("\n")[0][:100] if media.caption_text else f"Post by @{media.user.username}",
                "caption": media.caption_text or "",
                "timestamp": media.taken_at.isoformat() if media.taken_at else "",
                "likes": media.like_count or 0,
                "comments_count": media.comment_count or 0,
                "media_type": "CAROUSEL" if media.media_type == 8 else ("VIDEO" if media.media_type == 2 else "IMAGE"),
                "media_urls": media_urls,
                "thumbnail_url": str(media.thumbnail_url or (media_urls[0] if media_urls else "")),
                "downloaded_files": []
            }
            results.append(item)
        except LoginRequired:
            return jsonify({
                "success": False,
                "error": "Instagram requires authentication for this post/account. Please provide your Instagram sessionid cookie in Advanced Settings."
            }), 401
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    else:
        # Profile username
        username = query.lstrip("@").strip()
        try:
            user_id = cl.user_id_from_username(username)
            user_info = cl.user_info(user_id)
            profile_dict = {
                "username": user_info.username,
                "full_name": user_info.full_name,
                "biography": user_info.biography,
                "followers": user_info.follower_count,
                "is_private": user_info.is_private,
                "profile_pic_url": str(user_info.profile_pic_url),
                "mediacount": user_info.media_count,
            }

            medias = cl.user_medias(user_id, amount=max_posts)
            for m in medias:
                media_urls = []
                if m.media_type == 8 and m.resources:
                    for res in m.resources:
                        if res.thumbnail_url:
                            media_urls.append(str(res.thumbnail_url))
                else:
                    target = m.thumbnail_url or (m.video_url if m.media_type == 2 else None)
                    if target:
                        media_urls.append(str(target))

                if media_urls:
                    item = {
                        "url": f"https://www.instagram.com/p/{m.code}/",
                        "shortcode": m.code,
                        "username": user_info.username,
                        "full_name": user_info.full_name,
                        "title": (m.caption_text or "").split("\n")[0][:100] if m.caption_text else f"Post by @{user_info.username}",
                        "caption": m.caption_text or "",
                        "timestamp": m.taken_at.isoformat() if m.taken_at else "",
                        "likes": m.like_count or 0,
                        "comments_count": m.comment_count or 0,
                        "media_type": "CAROUSEL" if m.media_type == 8 else ("VIDEO" if m.media_type == 2 else "IMAGE"),
                        "media_urls": media_urls,
                        "thumbnail_url": str(m.thumbnail_url or media_urls[0]),
                        "profile_info": profile_dict,
                        "downloaded_files": []
                    }
                    results.append(item)

            if not results and user_info.profile_pic_url:
                # Add profile pic if private or 0 posts
                results.append({
                    "url": f"https://www.instagram.com/{username}/",
                    "username": user_info.username,
                    "full_name": user_info.full_name,
                    "title": f"@{username} Profile Picture",
                    "caption": user_info.biography or "",
                    "timestamp": "",
                    "likes": 0,
                    "comments_count": 0,
                    "media_type": "PROFILE_PIC",
                    "media_urls": [str(user_info.profile_pic_url)],
                    "thumbnail_url": str(user_info.profile_pic_url),
                    "profile_info": profile_dict,
                    "downloaded_files": []
                })

        except LoginRequired:
            return jsonify({
                "success": False,
                "error": f"@{username} is a private account or requires authentication. Please provide your Instagram sessionid in Advanced Settings."
            }), 401
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    if not results:
        return jsonify({"success": False, "error": "No photos found."}), 404

    LATEST_RESULTS = results
    total_photos = sum(len(r.get("media_urls", [])) for r in results)

    return jsonify({
        "success": True,
        "query": query,
        "posts_count": len(results),
        "total_photos": total_photos,
        "results": results
    })


@app.route("/api/download-zip", methods=["GET"])
def download_zip():
    global LATEST_RESULTS
    if not LATEST_RESULTS:
        return jsonify({"error": "No recent scrape results available."}), 400

    import requests
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
