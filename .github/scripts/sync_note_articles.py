"""Sync published note.com articles into this repository.

Fetches the creator's article list from note.com, and for any article not
already represented in this repo (matched by note.com key or by exact
title), fetches its full body and writes a new Markdown file.

This script only writes files; committing/pushing is handled by the
GitHub Actions workflow that invokes it.
"""

import glob
import html.parser
import json
import os
import re
import urllib.request

CREATOR = "cafsjapan"
LIST_URL = "https://note.com/api/v2/creators/{creator}/contents?kind=note&page={page}"
NOTE_URL = "https://note.com/api/v3/notes/{key}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cafsjapan-note-sync/1.0)"}


def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


class BodyToMarkdown(html.parser.HTMLParser):
    """Best-effort HTML -> Markdown converter for note.com's editor output."""

    SKIP_TAGS = {"table-of-contents", "script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip_depth = 0
        self.link_href = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "h3":
            self.out.append("\n\n## ")
        elif tag == "p":
            self.out.append("\n\n")
        elif tag == "a":
            href = dict(attrs).get("href", "")
            self.link_href = href
            self.out.append("[")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "hr":
            self.out.append("\n\n---\n\n")
        elif tag == "blockquote":
            self.out.append("\n> ")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "a" and self.link_href is not None:
            self.out.append(f"]({self.link_href})")
            self.link_href = None
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")

    def handle_data(self, data):
        if self.skip_depth:
            return
        self.out.append(data)

    def markdown(self):
        text = "".join(self.out)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def slugify_key(key):
    return re.sub(r"[^a-zA-Z0-9]+", "", key)


def already_present(key, title, repo_files):
    for path in repo_files:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        if key in content:
            return True
        first_heading = next(
            (line[2:].strip() for line in content.splitlines() if line.startswith("# ")),
            None,
        )
        if first_heading and first_heading == title:
            return True
    return False


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_files = [
        p for p in glob.glob(os.path.join(repo_root, "*.md")) if os.path.basename(p) != "CLAUDE.md"
    ]

    articles = []
    for page in (1, 2):
        try:
            data = fetch_json(LIST_URL.format(creator=CREATOR, page=page))
        except Exception as e:
            print(f"Failed to fetch article list page {page}: {e}")
            continue
        contents = data.get("data", {}).get("contents", []) or data.get("contents", [])
        if not contents:
            break
        articles.extend(contents)

    created = []
    for art in articles:
        key = art.get("key")
        title = art.get("name") or art.get("title")
        published_at = art.get("publish_at") or art.get("publishedAt") or art.get("created_at") or ""
        date_str = (published_at or "")[:10]
        if not key or not title:
            continue
        if already_present(key, title, repo_files):
            continue

        try:
            note_data = fetch_json(NOTE_URL.format(key=key))
        except Exception as e:
            print(f"Failed to fetch note body for {key}: {e}")
            continue
        body_html = note_data.get("data", {}).get("body", "")
        parser = BodyToMarkdown()
        parser.feed(body_html)
        body_md = parser.markdown()

        filename = f"{date_str or 'unknown-date'}-{slugify_key(key)}.md"
        filepath = os.path.join(repo_root, filename)
        if os.path.exists(filepath):
            continue

        meta = (
            "<!--\n"
            "投稿用メタ情報\n"
            f"- 公開日: {date_str}（自動同期スクリプトにより取得。note.comに実際に公開済み）\n"
            "- 記事の型: （要確認）\n"
            "- 備考: GitHub Actionsによる自動同期で作成されたファイルです。\n"
            "-->\n\n"
        )
        full = f"{meta}# {title}\n\n{body_md}\n\nnote.com公開URL: https://note.com/cafsjapan/n/{key}\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full)
        created.append(filename)
        repo_files.append(filepath)
        print(f"Created {filename}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as sf:
            if created:
                sf.write("## Synced articles\n\n")
                for f in created:
                    sf.write(f"- {f}\n")
            else:
                sf.write("## No new articles to sync\n")

    # Signal to the workflow whether there is anything to commit.
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"created={'true' if created else 'false'}\n")


if __name__ == "__main__":
    main()
