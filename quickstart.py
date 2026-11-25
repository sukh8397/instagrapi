#!/usr/bin/env python3
"""
Quickstart CLI for instagrapi - Fast Instagram Scraping & Media Downloader
"""

import sys
import os
import argparse
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError

def get_client(session_id=None, username=None, password=None):
    cl = Client()
    # Configure realistic settings
    cl.delay_range = [1, 3]
    
    if session_id:
        print(f"[*] Authenticating with session ID...")
        cl.login_by_sessionid(session_id)
        print("[+] Logged in successfully via sessionid!")
    elif username and password:
        print(f"[*] Logging in as @{username}...")
        cl.login(username, password)
        print("[+] Logged in successfully!")
        
    return cl

def download_post(cl, url, output_dir="downloads"):
    os.makedirs(output_dir, exist_ok=True)
    try:
        pk = cl.media_pk_from_url(url)
        print(f"[*] Found media PK: {pk}")
        info = cl.media_info(pk)
        print(f"[+] Title / Caption: {(info.caption_text or '')[:80]}...")
        print(f"[+] Author: @{info.user.username} | Likes: {info.like_count:,}")
        
        if info.media_type == 1:  # Photo
            path = cl.photo_download(pk, folder=output_dir)
            print(f"[+] Downloaded photo to: {path}")
        elif info.media_type == 2:  # Video
            path = cl.video_download(pk, folder=output_dir)
            print(f"[+] Downloaded video to: {path}")
        elif info.media_type == 8:  # Album / Carousel
            paths = cl.album_download(pk, folder=output_dir)
            print(f"[+] Downloaded {len(paths)} carousel items to: {output_dir}")
        else:
            path = cl.media_download(pk, folder=output_dir)
            print(f"[+] Downloaded media to: {path}")
            
    except LoginRequired:
        print("\n[!] Instagram requires login to view this media.")
        print("[!] Re-run with: python quickstart.py --session-id <your_sessionid> --url <url>")
    except Exception as e:
        print(f"[x] Error downloading media: {e}")

def scrape_user(cl, username, amount=5, output_dir="downloads"):
    os.makedirs(output_dir, exist_ok=True)
    try:
        user_id = cl.user_id_from_username(username)
        print(f"[*] Found user ID: {user_id} for @{username}")
        user_info = cl.user_info(user_id)
        print(f"[+] Profile: @{user_info.username} ({user_info.full_name})")
        print(f"[+] Followers: {user_info.follower_count:,} | Posts: {user_info.media_count}")
        print(f"[+] Is Private: {user_info.is_private}")
        
        print(f"[*] Fetching latest {amount} medias...")
        medias = cl.user_medias(user_id, amount=amount)
        print(f"[+] Found {len(medias)} medias!")
        for idx, m in enumerate(medias):
            print(f"  #{idx+1} [PK: {m.pk}] {m.thumbnail_url}")
            
    except LoginRequired:
        print(f"\n[!] Instagram requires login to view @{username}.")
        print("[!] Re-run with: python quickstart.py --session-id <your_sessionid> --user <username>")
    except Exception as e:
        print(f"[x] Error fetching user info: {e}")

def main():
    parser = argparse.ArgumentParser(description="Instagrapi Quickstart Scraper")
    parser.add_argument("--url", help="Instagram post/reel/carousel URL")
    parser.add_argument("--user", help="Instagram profile username")
    parser.add_argument("--amount", type=int, default=5, help="Number of posts to fetch for profile")
    parser.add_argument("--session-id", help="Instagram sessionid cookie value")
    parser.add_argument("--login", help="Instagram username for password login")
    parser.add_argument("--password", help="Instagram password")
    parser.add_argument("--dir", default="downloads", help="Output directory for downloads")
    args = parser.parse_args()

    if not args.url and not args.user:
        parser.print_help()
        print("\nExample commands:")
        print("  python quickstart.py --user natgeo")
        print("  python quickstart.py --url https://www.instagram.com/p/DFzL121P0qG/")
        print("  python quickstart.py --session-id YOUR_SESSION_ID --user harmandeep_5702")
        return

    cl = get_client(session_id=args.session_id, username=args.login, password=args.password)

    if args.url:
        download_post(cl, args.url, output_dir=args.dir)
    elif args.user:
        scrape_user(cl, args.user, amount=args.amount, output_dir=args.dir)

if __name__ == "__main__":
    main()
