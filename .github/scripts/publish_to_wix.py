import json
import os
import re
import sys
import urllib.request


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


def main():
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        content = f.read()

    # Strip leading HTML comment block (internal meta notes, not for public post)
    content = re.sub(r"^\s*<!--.*?-->\s*", "", content, flags=re.DOTALL)

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

    rich_content = {"nodes": build_rich_content(body_lines)}

    site_id = os.environ["WIX_SITE_ID"]
    member_id = os.environ["WIX_MEMBER_ID"]
    api_key = os.environ["WIX_API_KEY"]

    draft_body = json.dumps({
        "draftPost": {
            "title": title,
            "memberId": member_id,
            "richContent": rich_content,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://www.wixapis.com/blog/v3/draft-posts",
        data=draft_body,
        headers={
            "Authorization": api_key,
            "wix-site-id": site_id,
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        draft = json.loads(resp.read().decode("utf-8"))

    draft_id = draft["draftPost"]["id"]

    pub_req = urllib.request.Request(
        f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}/publish",
        data=b"{}",
        headers={
            "Authorization": api_key,
            "wix-site-id": site_id,
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(pub_req) as resp:
        published = json.loads(resp.read().decode("utf-8"))

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
            sf.write("\nStatus: published\n")


if __name__ == "__main__":
    main()
