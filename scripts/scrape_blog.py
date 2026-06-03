# -*- coding: utf-8 -*-
"""
缠中说禅新浪博客爬虫 / Chan Zhong Shuo Chan blog scraper.

遍历文章列表的所有分页，提取"教你炒股票"系列(共108课)及相关技术文章的链接，
下载正文并解析为纯文本，保存到 corpus/ 目录，同时生成 manifest.csv 索引。

博客地址: https://blog.sina.com.cn/s/articlelist_1215172700_0_<page>.html
"""
import csv
import os
import re
import shutil
import subprocess
import sys
import time

from bs4 import BeautifulSoup

# 新浪反爬WAF会对 python-requests 的 TLS 指纹返回 418, 但放行 curl。
# 故统一用系统 curl.exe 抓取, 再用 BeautifulSoup 解析。
CURL = shutil.which("curl") or shutil.which("curl.exe") or r"C:\Windows\System32\curl.exe"

BLOG_UID = "1215172700"
LIST_URL = "https://blog.sina.com.cn/s/articlelist_{uid}_0_{page}.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://blog.sina.com.cn/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
NUM_PAGES = 19
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORPUS_DIR = os.path.join(ROOT, "corpus")

ARTICLE_RE = re.compile(r"/s/blog_[0-9a-zA-Z]+\.html")
LESSON_RE = re.compile(r"教你炒股票\s*([0-9]+)?")
BLOG_TAG = "blog_486e105c"  # 作者博文URL前缀, 用于校验返回页非WAF拦截页


def normalize_url(href: str) -> str:
    """新浪链接常为协议相对 (//blog.sina.com.cn/...), 统一补成 https。"""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://"):
        return "https://" + href[len("http://"):]
    return href


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            p = subprocess.run(
                [CURL, "-s", "-L", "--max-time", "30",
                 "-A", HEADERS["User-Agent"],
                 "-H", "Accept-Language: " + HEADERS["Accept-Language"],
                 "-e", HEADERS["Referer"], url],
                capture_output=True, timeout=45,
            )
            text = p.stdout.decode("utf-8", errors="replace")
            # 校验: 返回页须含作者博文链接前缀, 以排除WAF拦截/挑战页
            if p.returncode == 0 and len(text) > 3000 and BLOG_TAG in text:
                return text
            last = "rc=%s len=%s" % (p.returncode, len(text))
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        time.sleep(1.0 * (i + 1))
    print("  !! failed %s (%s)" % (url, last), flush=True)
    return None


def enumerate_lessons():
    """遍历列表分页, 返回 {lesson_no: (title, url)} 以及其它技术相关文章列表。"""
    lessons = {}        # lesson_no(int) -> (title, url)
    seen_urls = set()
    for page in range(1, NUM_PAGES + 1):
        url = LIST_URL.format(uid=BLOG_UID, page=page)
        html = get(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        found = 0
        for a in soup.find_all("a"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if "教你炒股票" not in title:
                continue
            if not ARTICLE_RE.search(href or ""):
                continue
            href = normalize_url(href)
            if href in seen_urls:
                continue
            seen_urls.add(href)
            m = LESSON_RE.search(title)
            no = int(m.group(1)) if (m and m.group(1)) else -1
            # 保留首次出现 (列表从新到旧, 取已编号优先)
            if no >= 0 and no in lessons:
                continue
            if no < 0:
                no = -(len(lessons) + 1000)  # 未编号文章占位
            lessons[no] = (title, href)
            found += 1
        print("list page %2d: +%d lessons (total %d)" % (page, found, len(lessons)))
        time.sleep(1.0)
    return lessons


def parse_article(html):
    soup = BeautifulSoup(html, "lxml")
    # 标题
    title = ""
    t = soup.find("h2", class_=re.compile("titName")) or soup.find("title")
    if t:
        title = t.get_text(strip=True)
    # 正文容器: id=sina_keyword_ad_area2 (新浪博客正文)
    body = soup.find(id="sina_keyword_ad_area2")
    if body is None:
        body = soup.find("div", class_=re.compile("articalContent"))
    if body is None:
        return title, ""
    # 去除脚本/样式
    for bad in body.find_all(["script", "style"]):
        bad.decompose()
    text = body.get_text("\n", strip=True)
    # 清理多余空行
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return title, "\n".join(lines)


def safe_name(no, title):
    clean = re.sub(r"[\\/:*?\"<>|\n\r\t]", "_", title)[:60]
    if no >= 0:
        return "lesson_%03d_%s.txt" % (no, clean)
    return "extra_%s.txt" % clean


def main():
    # 重定向到 PowerShell 管道时默认编码为 GBK, 会因 \xa0 等字符崩溃; 强制 UTF-8。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(CORPUS_DIR, exist_ok=True)
    print("=== 枚举课程链接 ===")
    lessons = enumerate_lessons()
    numbered = sorted([n for n in lessons if n >= 0])
    print("\n共发现已编号课程 %d 篇, 范围 %s..%s" %
          (len(numbered), numbered[0] if numbered else "-", numbered[-1] if numbered else "-"))
    missing = [n for n in range(1, 109) if n not in lessons]
    print("缺失编号: %s" % (missing if missing else "无"))

    manifest = []
    print("\n=== 下载正文 ===")
    for no in sorted(lessons.keys()):
        title, url = lessons[no]
        fname = safe_name(no, title)
        path = os.path.join(CORPUS_DIR, fname)
        # 断点续传: 已存在且非空则跳过
        if os.path.exists(path) and os.path.getsize(path) > 0:
            manifest.append({"lesson": no if no >= 0 else "", "title": title,
                             "url": url, "file": fname,
                             "chars": os.path.getsize(path)})
            print("  [%s] 跳过(已存在) %s" % (str(no).rjust(3), title[:24]))
            continue
        html = get(url)
        if not html:
            continue
        atitle, text = parse_article(html)
        if not text:
            print("  !! 正文为空: %s" % url)
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write("标题: %s\n来源: %s\n%s\n\n%s\n" % (title, url, "=" * 40, text))
        manifest.append({"lesson": no if no >= 0 else "", "title": title,
                         "url": url, "file": fname, "chars": len(text)})
        print("  [%s] %s (%d zi)" % (str(no).rjust(3), title[:30], len(text)))
        time.sleep(0.6)

    manifest.sort(key=lambda r: (r["lesson"] == "", r["lesson"]))
    with open(os.path.join(CORPUS_DIR, "manifest.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["lesson", "title", "url", "file", "chars"])
        w.writeheader()
        w.writerows(manifest)
    print("\n完成: 下载 %d 篇, manifest.csv 已生成。" % len(manifest))


if __name__ == "__main__":
    sys.exit(main())
