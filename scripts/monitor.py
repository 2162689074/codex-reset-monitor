#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex 重置监控核心脚本。

抓取 https://aihot.news/codex-reset，提取量化状态，与基准对比；
检测到新的额度重置 / 重置卡发放 / 待生效公告变化时，用 QQ 邮箱 SMTP 发送告警邮件。

运行目录（--workdir）存放：
  smtp_config.json  发件配置（含授权码，权限 600）
  baseline.json     状态基准
  monitor.log       运行日志

用法：
  python3 monitor.py --workdir <目录> --init   # 仅建立基准
  python3 monitor.py --workdir <目录>          # 正常监控
"""
import os
import re
import sys
import json
import argparse
import smtplib
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

URL = "https://aihot.news/codex-reset"
DEFAULT_WORKDIR = os.path.expanduser("~/.codex_reset_monitor")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def paths(workdir):
    return {
        "cfg": os.path.join(workdir, "smtp_config.json"),
        "baseline": os.path.join(workdir, "baseline.json"),
        "log": os.path.join(workdir, "monitor.log"),
    }


def log(workdir, msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(paths(workdir)["log"], "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def html_to_lines(raw):
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "html.parser")
        return [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    except ImportError:
        from html.parser import HTMLParser

        class P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []

            def handle_data(self, d):
                self.parts.append(d)

        p = P()
        p.feed(raw)
        return [l.strip() for l in "\n".join(p.parts).split("\n") if l.strip()]


def fetch_lines():
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")
    return html_to_lines(raw)


def extract_state(lines):
    text = "\n".join(lines)
    s = {}

    def grab(pattern):
        m = re.search(pattern, text)
        return m.group(1) if m else None

    qr = grab(r"近\s*90\s*天额度重置\s*\n\s*(\d+)\s*次")
    s["quota_reset_count_90d"] = int(qr) if qr else None

    rc = grab(r"近\s*90\s*天发重置卡\s*\n\s*(\d+)\s*次")
    s["reset_card_count_90d"] = int(rc) if rc else None

    s["last_quota_reset"] = grab(r"上次额度重置\s*\n\s*(\d+\s*月\s*\d+\s*日)")

    # 顶部状态行：以“等待”开头且含“生效”（如“等待额度重置生效”）
    pending = None
    for l in lines:
        if l.startswith("等待") and "生效" in l:
            pending = l
            break
    # 兜底：含“等待生效”，但排除日历统计（含“次”）与详情标题（含“·”）
    if not pending:
        for l in lines:
            if "等待生效" in l and "次" not in l and "·" not in l:
                pending = l
                break
    s["pending_line"] = pending

    last_card = None
    for l in lines:
        if l.startswith("上一次重置卡发放") or l.startswith("上一次重置"):
            last_card = l
            break
    s["last_card_line"] = last_card

    banner = None
    for l in lines:
        if ("正在发放" in l or "正在加载" in l or "正在进行" in l or "正处在" in l) and len(l) <= 40:
            banner = l
            break
    s["banner_line"] = banner

    # 预计时间：“预计”常单独成行，时间窗在紧随其后的一行；合并并去重
    estimate_lines = []
    seen_est = set()
    for i, l in enumerate(lines):
        if l.startswith("预计"):
            txt = l.strip()
            if txt == "预计" and i + 1 < len(lines):
                txt = "预计 " + lines[i + 1].strip()
            key = re.sub(r"\s+", "", txt)
            if key not in seen_est:
                seen_est.add(key)
                estimate_lines.append(txt)
    s["estimate_lines"] = estimate_lines

    # Tibo 发帖时间（X 平台格式 M/D HH:MM，北京时间）
    time_re = r"\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}"

    # 排除页面底部 AIHOT 自身的“最近检查/尝试/采集/核验”时间
    excluded = set()
    for i, l in enumerate(lines):
        if any(k in l for k in ("最近检查", "最近尝试", "最近采集", "最近完整核验")):
            for j in range(i, min(i + 3, len(lines))):
                mm = re.fullmatch(time_re, lines[j])
                if mm:
                    excluded.add((j, mm.group(0)))

    post_times = []
    for i, l in enumerate(lines):
        for m in re.finditer(time_re, l):
            t = m.group(0)
            if (i, t) in excluded:
                continue
            if t not in post_times:
                post_times.append(t)
    s["post_times"] = post_times

    def nearby_time(idx, span=4):
        m = re.search(time_re, lines[idx])
        if m:
            return m.group(0)
        for j in range(idx + 1, min(idx + span, len(lines))):
            mm = re.fullmatch(time_re, lines[j])
            if mm:
                return mm.group(0)
        return None

    # 确认帖时间：“确认帖”同行或其后紧邻的时间
    confirm_time = None
    for i, l in enumerate(lines):
        if "确认帖" in l:
            confirm_time = nearby_time(i)
            if confirm_time:
                break
    s["confirm_post_time"] = confirm_time

    # 最早相关帖时间
    earliest = None
    for i, l in enumerate(lines):
        if "最早" in l:
            earliest = nearby_time(i)
            if earliest:
                break
    s["earliest_post_time"] = earliest
    return s


def diff(old, new):
    events = []

    o, n = old.get("quota_reset_count_90d"), new.get("quota_reset_count_90d")
    if o is not None and n is not None and n > o:
        events.append("检测到新的<b>额度重置</b>：近90天额度重置次数 %d → %d" % (o, n))

    o, n = old.get("reset_card_count_90d"), new.get("reset_card_count_90d")
    if o is not None and n is not None and n > o:
        events.append("检测到新的<b>重置卡发放</b>：近90天发重置卡次数 %d → %d" % (o, n))

    o, n = old.get("last_quota_reset"), new.get("last_quota_reset")
    if o and n and o != n:
        events.append("<b>上次额度重置日期</b>更新：%s → %s" % (o, n))

    o, n = old.get("pending_line"), new.get("pending_line")
    if o != n:
        if n and "没有" not in n:
            events.append("出现<b>等待生效</b>的重置/发卡：%s" % n)
        elif o and "没有" not in o and n and "没有" in n:
            events.append("原等待生效的重置/发卡<b>已结束</b>（已确认或已过预计时间）")
        elif o != n:
            events.append("等待状态变化：%s → %s" % (o, n))

    o, n = old.get("banner_line"), new.get("banner_line")
    if o and not n:
        events.append("原状态「%s」<b>已结束</b>（可能已确认到账）" % o)
    elif n and not o:
        events.append("出现新状态：%s" % n)

    o, n = old.get("last_card_line"), new.get("last_card_line")
    if o and n and o != n:
        events.append("<b>重置卡发放记录</b>更新：%s → %s" % (o, n))

    seen = set()
    uniq = []
    for e in events:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def build_mail_html(events, new):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lis = "".join("<li>%s</li>" % e for e in events)
    est = "；".join(new.get("estimate_lines") or []) or "无"

    ct = new.get("confirm_post_time")
    earliest = new.get("earliest_post_time")
    pts = new.get("post_times") or []
    tibo_parts = []
    if ct:
        tibo_parts.append("Tibo 确认帖时间：%s（北京时间；确认帖时间不代表精确到账时间）" % ct)
    if earliest:
        tibo_parts.append("最早相关帖时间：%s（北京时间）" % earliest)
    if not ct and pts:
        tibo_parts.append("Tibo 预告帖时间：%s（北京时间；当前为已宣布、等待生效，尚未确认到账）" % "、".join(pts))
    elif not tibo_parts and pts:
        tibo_parts.append("Tibo 发帖时间：%s（北京时间）" % "、".join(pts))
    if not tibo_parts:
        tibo_parts.append("Tibo 发帖时间：页面未显示")
    tibo_block = "".join("<p><b>%s</b></p>" % p for p in tibo_parts)

    return (
        "<p>监控页面 <b>%s</b> 出现重置/发卡动态：</p>"
        "<ul>%s</ul>"
        "%s"
        "<p><b>当前状态快照</b>：</p>"
        "<ul>"
        "<li>近90天额度重置：%s 次</li>"
        "<li>近90天发重置卡：%s 次</li>"
        "<li>上次额度重置：%s</li>"
        "<li>等待状态：%s</li>"
        "<li>预计时间：%s</li>"
        "<li>Tibo 相关帖子时间：%s</li>"
        "</ul>"
        '<p>页面：<a href="%s">Tibo 重置监控 · AIHOT</a>（全部为北京时间）</p>'
        "<p>检测时间：%s</p>"
    ) % (
        URL, lis, tibo_block,
        new.get("quota_reset_count_90d"),
        new.get("reset_card_count_90d"),
        new.get("last_quota_reset"),
        new.get("pending_line") or "无",
        est,
        "、".join(pts) or (ct or "页面未显示"),
        URL, now,
    )


def _connect(cfg):
    if cfg.get("use_ssl", True):
        server = smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], timeout=30)
    else:
        server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=30)
        server.starttls()
    server.login(cfg["sender"], cfg["auth_code"])
    return server


def verify_login(cfg):
    """仅验证授权码能否登录，不发送任何邮件。"""
    server = _connect(cfg)
    server.quit()


def send_mail(cfg, subject, html_body):
    msg = MIMEText(html_body, "html", "utf-8")
    msg["From"] = formataddr((str(Header("Codex重置监控", "utf-8")), cfg["sender"]))
    msg["To"] = cfg["recipient"]
    msg["Subject"] = Header(subject, "utf-8")
    server = _connect(cfg)
    try:
        server.sendmail(cfg["sender"], [cfg["recipient"]], msg.as_string())
    finally:
        server.quit()


def load_config(workdir):
    with open(paths(workdir)["cfg"], "r", encoding="utf-8") as f:
        return json.load(f)


def save_baseline(workdir, state):
    payload = {"state": state, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with open(paths(workdir)["baseline"], "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_baseline(workdir):
    with open(paths(workdir)["baseline"], "r", encoding="utf-8") as f:
        return json.load(f).get("state", {})


def run(workdir, init=False):
    os.makedirs(workdir, exist_ok=True)
    try:
        lines = fetch_lines()
    except Exception as e:
        log(workdir, "抓取失败：%r" % e)
        return 2

    new = extract_state(lines)
    log(workdir, "抓取成功：%s" % json.dumps(new, ensure_ascii=False))

    if init or not os.path.exists(paths(workdir)["baseline"]):
        save_baseline(workdir, new)
        log(workdir, "已建立基准（init），不发邮件。")
        return 0

    old = load_baseline(workdir)
    events = diff(old, new)
    if not events:
        save_baseline(workdir, new)
        log(workdir, "无变化，不发邮件。")
        return 0

    cfg = load_config(workdir)
    html = build_mail_html(events, new)
    try:
        send_mail(cfg, "【Codex重置】检测到重置/发卡动态", html)
    except Exception as e:
        log(workdir, "发邮件失败：%r（保留旧基准，下次重试）" % e)
        return 3

    save_baseline(workdir, new)
    log(workdir, "已发送告警邮件，共 %d 条事件，并更新基准。" % len(events))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR)
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args()
    sys.exit(run(os.path.abspath(args.workdir), init=args.init))


if __name__ == "__main__":
    main()
