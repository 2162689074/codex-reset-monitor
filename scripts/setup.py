#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex 重置监控一键部署脚本。

根据用户提供的 QQ 邮箱地址与 SMTP 授权码：
  1. 创建运行目录并写入 smtp_config.json（权限 600）；
  2. 抓取页面、初始化状态基准；
  3. 可选发送一封测试邮件验证通路。

部署完成后，应由 Agent 用定时任务（cron）按固定频率调用：
  python3 <scripts_dir>/monitor.py --workdir <workdir>

用法：
  python3 setup.py --qq-mail xxx@qq.com --auth-code XXXXXXXXXXXXXXXX \
      [--recipient yyy@qq.com] [--workdir 目录] [--send-test]
"""
import os
import sys
import json
import argparse

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import monitor  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qq-mail", required=True, help="发件 QQ 邮箱地址")
    parser.add_argument("--auth-code", required=True, help="QQ 邮箱 16 位 SMTP 授权码")
    parser.add_argument("--recipient", help="告警收件邮箱，默认等于发件邮箱")
    parser.add_argument("--workdir", default=monitor.DEFAULT_WORKDIR, help="运行目录")
    parser.add_argument("--send-test", action="store_true", help="部署后发送测试邮件")
    args = parser.parse_args()

    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)

    cfg = {
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "use_ssl": True,
        "sender": args.qq_mail.strip(),
        "auth_code": args.auth_code.strip(),
        "recipient": (args.recipient or args.qq_mail).strip(),
    }
    cfg_path = monitor.paths(workdir)["cfg"]
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(cfg_path, 0o600)
    print("WORKDIR=%s" % workdir)
    print("CONFIG_WRITTEN=%s" % cfg_path)

    rc = monitor.run(workdir, init=True)
    if rc != 0:
        print("BASELINE_INIT_FAILED rc=%d" % rc, file=sys.stderr)
        sys.exit(rc)
    print("BASELINE_INIT_OK")

    # 验证授权码：仅登录，不发送任何邮件
    try:
        monitor.verify_login(cfg)
        print("LOGIN_OK")
    except Exception as e:
        print("LOGIN_FAILED: %r" % e, file=sys.stderr)
        sys.exit(4)

    if args.send_test:
        test_html = (
            "<p>这是一封<strong>测试邮件</strong>，用于验证 QQ 邮箱 SMTP 发信通路。</p>"
            "<p>收到此邮件，说明监控检测到 Codex 重置后可正常向你发送告警邮件。</p>"
            '<p>监控页面：<a href="%s">Tibo 重置监控 · AIHOT</a></p>'
        ) % monitor.URL
        try:
            monitor.send_mail(cfg, "【通路测试】Codex重置监控已就绪", test_html)
            print("TEST_MAIL_OK")
        except Exception as e:
            print("TEST_MAIL_FAILED: %r" % e, file=sys.stderr)
            sys.exit(5)

    print("MONITOR_COMMAND=python3 %s --workdir %s" % (
        os.path.join(SCRIPTS_DIR, "monitor.py"), workdir))


if __name__ == "__main__":
    main()
