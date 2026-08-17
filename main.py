"""
astrbot_plugin_dailystory — 今日群聊小故事

读取当天群聊消息记录，以提问的用户为主角，调用 AI 生成一段有趣的小故事。
仅支持 aiocqhttp (OneBot v11) 平台（需调用 get_group_msg_history）。
"""

from __future__ import annotations

import time
from datetime import datetime, time as dtime
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
        AiocqhttpMessageEvent,
    )
except Exception:  # pragma: no cover - 仅在缺少 aiocqhttp 平台时兜底
    AiocqhttpMessageEvent = None  # type: ignore[assignment]


def _is_aiocqhttp(event: AstrMessageEvent) -> bool:
    """判断当前事件是否来自 aiocqhttp(OneBot) 平台。"""
    return AiocqhttpMessageEvent is not None and isinstance(
        event, AiocqhttpMessageEvent
    )


def _extract_plain_text(message: Any) -> str:
    """从 OneBot 原始 message 字段提取纯文本内容。

    OneBot v11 的 message 字段可能是消息段数组，每个段形如
    {"type": "text", "data": {"text": "..."}} 或
    {"type": "at", "data": {"qq": "12345"}} 等。
    这里只把 text 段拼起来，其他段以占位符表示，保留可读性。
    """
    if isinstance(message, str):
        return message

    parts: list[str] = []
    if isinstance(message, list):
        for seg in message:
            if not isinstance(seg, dict):
                continue
            seg_type = seg.get("type", "")
            data = seg.get("data", {}) or {}
            if seg_type == "text":
                parts.append(str(data.get("text", "")))
            elif seg_type == "at":
                parts.append(f"@{data.get('qq', '?')}")
            elif seg_type in ("image", "mface", "flash"):
                parts.append("[图片]")
            elif seg_type == "face":
                parts.append("[表情]")
            elif seg_type == "reply":
                parts.append("[回复]")
            elif seg_type == "record":
                parts.append("[语音]")
            elif seg_type == "video":
                parts.append("[视频]")
            elif seg_type == "file":
                parts.append(f"[文件:{data.get('file', '')}]")
            else:
                parts.append(f"[{seg_type}]")
    return "".join(parts)


@register(
    "astrbot_plugin_dailystory", "AlienStar", "今日群聊小故事", "1.0.0"
)
class DailyStoryPlugin(Star):
    """读取当天群聊消息，以提问者为主角生成小故事。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config or {}
        logger.info("DailyStoryPlugin 已加载")

    @filter.command("今日故事", alias={"今日群聊故事", "群聊小故事", "今日小故事"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def daily_story(self, event: AstrMessageEvent):
        """读取当天群聊消息并以提问者为主角生成小故事。"""
        if not _is_aiocqhttp(event):
            yield event.plain_result("❌ 该功能仅在 QQ (aiocqhttp/OneBot) 平台可用。")
            return

        group_id = event.get_group_id() or ""
        if not group_id:
            yield event.plain_result("❌ 当前不在群聊环境中，无法获取群消息。")
            return

        sender_name = event.get_sender_name() or "主角"

        # 先回复一句正在处理
        yield event.plain_result(f"📖 正在读取群 {group_id} 今日聊天记录，稍等一下~")

        # 1. 拉取群聊消息
        try:
            messages = await self._fetch_today_messages(event, group_id)
        except Exception as e:
            logger.error(f"获取群消息历史失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取群消息历史失败：{e}")
            return

        if not messages:
            yield event.plain_result("今天群里还没有聊天记录呢，生成不出故事啦~")
            return

        logger.info(f"群 {group_id} 今日共获取到 {len(messages)} 条消息")

        # 2. 整理为对话剧本
        script = self._build_dialogue_script(messages)

        # 3. 构造提示词并调用 LLM
        prompt = self._build_prompt(sender_name, script)

        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            if not provider_id:
                yield event.plain_result("❌ 未找到当前会话配置的 AI 模型，请先在后台配置。")
                return

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            story = (llm_resp.completion_text or "").strip()
        except Exception as e:
            logger.error(f"调用 AI 生成故事失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ AI 生成故事失败：{e}")
            return

        if not story:
            yield event.plain_result("AI 没有给出故事内容，再试一次吧~")
            return

        # 4. 输出故事
        yield event.plain_result(story)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _fetch_today_messages(
        self, event: AstrMessageEvent, group_id: str
    ) -> list[dict[str, Any]]:
        """从 OneBot 拉取当天的群聊消息（返回升序的消息列表）。

        使用 get_group_msg_history 向历史方向翻页，直到消息时间早于今天 00:00。
        """
        max_messages = int(self.config.get("max_messages", 80))
        if max_messages <= 0:
            max_messages = 80

        # 计算"今天 00:00:00"的时间戳
        today_start = datetime.combine(datetime.now().date(), dtime.min).timestamp()

        collected: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        message_seq = 0  # 从最新开始往回翻
        page = 0

        while len(collected) < max_messages:
            page += 1
            try:
                resp = await event.bot.api.call_action(
                    "get_group_msg_history",
                    group_id=int(group_id),
                    message_seq=message_seq,
                )
            except Exception as e:
                logger.warning(f"第 {page} 页 get_group_msg_history 调用失败: {e}")
                break

            messages = resp.get("messages", []) if isinstance(resp, dict) else []
            if not messages:
                break

            oldest_time_in_page = None
            oldest_seq_in_page = None

            for m in messages:
                msg_id = m.get("message_id")
                ts = m.get("time", 0)
                try:
                    ts = int(ts)
                except (TypeError, ValueError):
                    ts = 0

                # 记录本页最早消息，用于翻页
                if oldest_time_in_page is None or ts < oldest_time_in_page:
                    oldest_time_in_page = ts
                    # 优先用 message_seq 翻页（OneBot 扩展字段），回退 message_id
                    oldest_seq_in_page = (
                        m.get("message_seq")
                        or m.get("message_id")
                        or message_seq
                    )

                # 去重（按 message_id；无 id 的消息不去重但通常极少）
                if msg_id is not None:
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)

                # 超过上限就停止
                if len(collected) >= max_messages:
                    break

                collected.append(m)

            # 判断是否已经翻到今天之前
            if oldest_time_in_page is not None and oldest_time_in_page < today_start:
                break

            # 翻页：把 message_seq 设为本页最早消息的 message_id
            if oldest_seq_in_page is None:
                break
            # OneBot 实现中，把 message_seq 设为某条消息 id 会返回该消息及之前的历史
            if oldest_seq_in_page == message_seq:
                # 没有进展，避免死循环
                break
            message_seq = oldest_seq_in_page

            # 安全阀：防止异常情况下无限翻页
            if page > 50:
                break

        # 按时间升序，只保留今天 00:00 之后的
        today_messages = [
            m for m in collected if int(m.get("time", 0) or 0) >= today_start
        ]
        today_messages.sort(key=lambda m: int(m.get("time", 0) or 0))
        return today_messages

    def _build_dialogue_script(
        self, messages: list[dict[str, Any]]
    ) -> str:
        """把 OneBot 消息列表整理为可读对话剧本。"""
        lines: list[str] = []
        for m in messages:
            sender = m.get("sender", {}) or {}
            nickname = (
                sender.get("card")
                or sender.get("nickname")
                or str(m.get("user_id", "?"))
            )
            ts = int(m.get("time", 0) or 0)
            time_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "??:??:??"
            text = _extract_plain_text(m.get("message", ""))
            if not text:
                continue
            # 限制单条消息长度，避免 prompt 过长
            if len(text) > 200:
                text = text[:200] + "……"
            lines.append(f"[{time_str}] {nickname}: {text}")
        return "\n".join(lines)

    def _build_prompt(self, protagonist: str, dialogue: str) -> str:
        """构造发送给 LLM 的提示词。"""
        style = self.config.get("story_style", "轻松幽默的奇幻冒险") or "轻松幽默的奇幻冒险"
        length_desc = self.config.get("story_length", "300-600字") or "300-600字"
        language = self.config.get("story_language", "中文") or "中文"

        prompt = (
            f"你是一位富有创造力的小说家。请根据下面提供的某 QQ 群今天真实发生的聊天记录，"
            f"创作一段{style}风格的小故事。\n\n"
            f"【要求】\n"
            f"1. 故事以「{protagonist}」作为主角，TA 是今天在群里发起提问的人。\n"
            f"2. 群里其他发言者可以作为配角出现，可以适当改编他们的发言为故事对白。\n"
            f"3. 故事长度约 {length_desc}。\n"
            f"4. 语言：{language}。\n"
            f"5. 故事要有趣、有画面感，可以有适当的戏剧冲突和温暖结尾。\n"
            f"6. 不要输出任何解释说明、不要复述聊天记录，直接输出故事正文即可。\n\n"
            f"【今天的群聊记录】\n"
            f"{dialogue}\n\n"
            f"请开始创作故事："
        )
        return prompt
