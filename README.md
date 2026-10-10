# codex-reset-monitor

一个 AI Agent Skill：定时抓取 [Tibo 重置监控页](https://aihot.news/codex-reset)，一旦出现新的 Codex 额度重置、重置卡发放或待生效公告，就自动通过你的 QQ 邮箱 SMTP 发一封告警邮件。

## 效果

- 每小时检查一次（频率可自定义）
- 只在真正发生重置/发卡时发邮件，平时不打扰
- 邮件里写明 Tibo 发帖时间（确认帖时间、最早相关帖时间，北京时间）
- 无新重置时静默执行；授权码只存在本地、不写进任务指令

## 安装

把整个 `codex-reset-monitor` 文件夹放进你的 Agent 的 user skills 目录（与其他自定义 skill 同级），然后对 Agent 说：

> 帮我监控 Codex 重置，重置时发我 QQ 邮箱。

Agent 会引导你提供 QQ 邮箱和 16 位 SMTP 授权码，自动完成部署并创建定时任务。

### 获取 QQ 邮箱授权码

登录 QQ 邮箱网页版 →「设置」→「账户」→ 开启「IMAP/SMTP 服务」→ 按提示发短信验证 → 得到 16 位授权码。

## 手动使用（不依赖 Agent）

```bash
# 1. 部署（写入本地配置、初始化基准、验证授权码，不发邮件）
python3 scripts/setup.py --qq-mail you@qq.com --auth-code XXXXXXXXXXXXXXXX

# 2. 每小时运行一次监控（可用 crontab / 系统定时任务）
python3 scripts/monitor.py
```

检测到重置时会自动发信；无变化时静默退出。

## 文件

- `SKILL.md` — Skill 定义（给 AI Agent 读）
- `scripts/setup.py` — 一键部署
- `scripts/monitor.py` — 抓取、对比、发信核心逻辑

## 说明

监控页面为公开页面，无需登录。本项目非 OpenAI 官方页面。
