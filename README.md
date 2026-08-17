# 今日群聊小故事 · astrbot_plugin_dailystory

读取当天群聊消息记录，以提问的用户为主角，调用 AI 生成一段并不生动也不有趣的小故事。

## 功能介绍

在 QQ 群里发送 `/今日故事`，插件会：

1. 通过 OneBot 协议端调用 `get_group_msg_history`，向历史方向翻页拉取**当天**（今天 00:00 起）的群聊消息。
2. 把消息整理成可读对话剧本（时间 + 昵称 + 文本，图片/语音等以占位符表示）。
3. 以**发起指令的用户**为主角，把群聊记录作为素材，调用 AstrBot 当前会话配置的 AI 模型生成一段小故事。
4. 直接在群里输出故事正文。

故事风格、长度、语言、读取消息条数上限均可在 WebUI 插件配置页调整。

## 指令

| 指令 | 别名 | 说明 |
|---|---|---|
| `/今日故事` | `/今日群聊故事`、`/群聊小故事`、`/今日小故事` | 读取当天群聊记录并生成以提问者为主角的小故事 |

> 仅在**群聊**中触发，私聊不响应。

## 配置项（WebUI 插件管理 → 今日群聊小故事）

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `story_style` | 故事风格基调 | 轻松幽默的奇幻冒险 |
| `story_length` | 故事长度（传给模型的字数描述） | 300-600字 |
| `max_messages` | 读取消息条数上限（按页翻取，每页20条） | 80 |
| `story_language` | 生成故事使用的语言 | 中文 |

## 环境要求

- AstrBot >= 4.5.0
- 平台：仅支持 **aiocqhttp**（OneBot v11，如 NapCat / Lagrange 等）
- 协议端需支持 `get_group_msg_history` 接口
- 需在 AstrBot 后台配置好至少一个 AI 聊天模型（插件使用当前会话配置的模型，无需单独填 API Key）

## 安装

把 `astrbot_plugin_dailystory` 文件夹放入 `AstrBot/data/plugins/`，在 WebUI「插件管理」中重载插件即可。

## 目录结构

```
astrbot_plugin_dailystory/
├─ main.py              # 插件主代码
├─ metadata.yaml        # 插件元数据
├─ _conf_schema.json    # 可视化配置 Schema
├─ requirements.txt     # 无第三方依赖
├─ README.md            # 本文件
└─ .gitignore
```

## 工作流程

```
用户在群内发送 /今日故事
        │
        ▼
插件判断平台是否为 aiocqhttp ──否──▶ 提示不支持
        │是
        ▼
调用 get_group_msg_history 翻页拉取今日消息（按时间升序）
        │
        ▼
整理为对话剧本 [HH:MM:SS] 昵称: 文本
        │
        ▼
构造提示词（以提问者为主角 + 剧本 + 风格/长度/语言）
        │
        ▼
self.context.llm_generate() 调用当前会话 AI 模型
        │
        ▼
在群里输出故事正文
```

## 许可

MIT
