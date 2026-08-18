import json
import os
import re
import sys
import urllib.request
import urllib.parse


def build_rich_content(body_lines):
    nodes = []
    node_id = 0
    for raw_line in body_lines:
        line = raw_line.rstrip("\n")
        if line.strip() == "" or line.strip() == "---":
            continue
        node_id += 1
        if line.startswith("## "):
            text = line[3:].strip()
            nodes.append({
                "type": "HEADING",
                "id": f"h{node_id}",
                "nodes": [{
                    "type": "TEXT",
                    "id": f"h{node_id}t",
                    "nodes": [],
                    "textData": {"text": text, "decorations": []},
                }],
                "headingData": {"level": 2},
            })
        else:
            nodes.append({
                "type": "PARAGRAPH",
                "id": f"p{node_id}",
                "nodes": [{
                    "type": "TEXT",
                    "id": f"p{node_id}t",
                    "nodes": [],
                    "textData": {"text": line, "decorations": []},
                }],
                "paragraphData": {},
            })
    return nodes


def http_json(url, headers=None, data=None, method="GET"):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_image_keyword(raw_content):
    m = re.search(r"画像キーワード[:：]\s*(.+)", raw_content)
    if m:
        return m.group(1).strip()
    return None


def fetch_and_upload_hero_image(keyword, site_id, wix_api_key):
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not unsplash_key or not keyword:
        return None, None

    query = urllib.parse.quote(keyword)
    search = http_json(
        f"https://api.unsplash.com/search/photos?query={query}&per_page=1&orientation=landscape",
        headers={"Authorization": f"Client-ID {unsplash_key}"},
    )
    results = search.get("results") or []
    if not results:
        return None, None
    photo = results[0]

    # Unsplash API guideline: trigger a download event when a photo is used.
    download_location = photo.get("links", {}).get("download_location")
    if download_location:
        try:
            http_json(download_location, headers={"Authorization": f"Client-ID {unsplash_key}"})
        except Exception:
            pass

    image_url = photo["urls"]["regular"]
    photographer = photo.get("user", {}).get("name", "Unsplash")
    photographer_url = photo.get("user", {}).get("links", {}).get("html", "https://unsplash.com")

    req = urllib.request.Request(image_url, headers={"User-Agent": "cafsjapan-note-bot/1.0"})
    with urllib.request.urlopen(req) as resp:
        image_bytes = resp.read()

    gen = http_json(
        "https://www.wixapis.com/site-media/v1/files/generate-upload-url",
        headers={
            "Authorization": wix_api_key,
            "wix-site-id": site_id,
            "Content-Type": "application/json",
        },
        data=json.dumps({"mimeType": "image/jpeg", "fileName": f"{re.sub(r'[^a-zA-Z0-9]+', '-', keyword)[:40]}.jpg"}).encode("utf-8"),
        method="POST",
    )
    upload_url = gen["uploadUrl"]

    up_req = urllib.request.Request(
        upload_url,
        data=image_bytes,
        headers={"Content-Type": "image/jpeg"},
        method="PUT",
    )
    with urllib.request.urlopen(up_req) as resp:
        uploaded = json.loads(resp.read().decode("utf-8"))

    media_id = uploaded["file"]["id"]
    return media_id, {"name": photographer, "url": photographer_url}


def main():
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        raw_content = f.read()

    image_keyword = find_image_keyword(raw_content)

    # Strip leading HTML comment block (internal meta notes, not for public post)
    content = re.sub(r"^\s*<!--.*?-->\s*", "", raw_content, flags=re.DOTALL)

    lines = content.splitlines()
    title = None
    body_lines = []
    for line in lines:
        if title is None and line.startswith("# "):
            title = line[2:].strip()
            continue
        body_lines.append(line)

    if not title:
        title = os.path.basename(path)

    nodes = build_rich_content(body_lines)

    site_id = os.environ["WIX_SITE_ID"]
    member_id = os.environ["WIX_MEMBER_ID"]
    api_key = os.environ["WIX_API_KEY"]

    media_id = None
    attribution = None
    try:
        media_id, attribution = fetch_and_upload_hero_image(image_keyword, site_id, api_key)
    except Exception as e:
        print(f"Hero image step failed, continuing without image: {e}", file=sys.stderr)

    if attribution:
        nodes.append({
            "type": "PARAGRAPH",
            "id": "p-image-credit",
            "nodes": [{
                "type": "TEXT",
                "id": "p-image-credit-t",
                "nodes": [],
                "textData": {
                    "text": f"画像: Photo by {attribution['name']} on Unsplash ({attribution['url']})",
                    "decorations": [],
                },
            }],
            "paragraphData": {},
        })

    draft_post = {
        "title": title,
        "memberId": member_id,
        "richContent": {"nodes": nodes},
    }
    if media_id:
        draft_post["media"] = {
            "wixMedia": {"image": {"id": media_id}},
            "displayed": True,
            "custom": True,
        }

    draft_body = json.dumps({"draftPost": draft_post}).encode("utf-8")

    draft = http_json(
        "https://www.wixapis.com/blog/v3/draft-posts",
        headers={
            "Authorization": api_key,
            "wix-site-id": site_id,
            "Content-Type": "application/json; charset=utf-8",
        },
        data=draft_body,
        method="POST",
    )

    draft_id = draft["draftPost"]["id"]

    published = http_json(
        f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}/publish",
        headers={
            "Authorization": api_key,
            "wix-site-id": site_id,
            "Content-Type": "application/json; charset=utf-8",
        },
        data=b"{}",
        method="POST",
    )

    print(json.dumps(published, ensure_ascii=False, indent=2))

    slug = None
    post = published.get("post") or published.get("draftPost") or {}
    slug = post.get("slug")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as sf:
            sf.write(f"## Wix publish result\n\nTitle: {title}\n\n")
            if slug:
                sf.write(f"URL: https://www.cafsjapan.com/post/{slug}\n")
            sf.write(f"\nHero image: {'yes' if media_id else 'no (no keyword or fetch failed)'}\n")
            sf.write("\nStatus: published\n")


if __name__ == "__main__":
    main()
