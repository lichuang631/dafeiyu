"""主人过稿后自动发表并投稿，保存阶段，防止重复发表。"""

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from astrbot.api import logger

from .contribution import (
    REVIEW_STATES,
    ContributionError,
    NativeContribution,
    QuotaExhausted,
)


def save_ledger(path: Path, ledger: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def check_reviewed_content(draft, record: dict):
    if record.get("sha256") != hashlib.sha256(draft.content.encode()).hexdigest():
        raise ContributionError("草稿正文已变化，请重新生成并审核后再发")
    images = [item for item in record.get("sources", []) if item.get("image_path")]
    if len(images) != len(draft.media):
        raise ContributionError("草稿配图已变化，请重新审核")
    for source, media in zip(images, draft.media):
        path = Path(source["image_path"])
        if (
            not path.is_file()
            or path.stat().st_size > 3_000_000
            or path.as_uri() != media.get("source")
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != source.get("image_sha256")
        ):
            raise ContributionError("审核时的配图已缺失或变化，请重新生成")


def ordinary_publication_message(draft_id: int) -> str:
    return (
        f"稿件 #{draft_id} 已发表到普通 QQ 空间。发表时空友爱看额度已用完，本条未投稿。"
        f"以后需要补投时发 /补投稿 {draft_id}，只补投这条原动态，不会重新发表。"
    )


def mark_ordinary_publication(path: Path, ledger: dict, record: dict):
    record["contribution_state"] = "ordinary_only"
    record["ordinary_reason"] = "quota_exhausted"
    record["ordinary_recorded_at"] = datetime.now(UTC).isoformat()
    save_ledger(path, ledger)


async def review_message(plugin, event):
    message = event.get_message_str().strip()
    match = re.fullmatch(r"/?(过稿|通过稿件|通过投稿|补投稿|投稿状态)\s+(\d+)", message)
    if not match:
        return
    action, draft_id = match[1], int(match[2])
    path = plugin.data_dir / "sources.json"
    try:
        ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        event.stop_event()
        yield event.plain_result("稿件来源记录暂不可用，已停止发表，稍后再试。")
        return
    if str(draft_id) not in ledger:
        if action in ("补投稿", "投稿状态"):
            event.stop_event()
            yield event.plain_result("这个编号不是我准备的空间草稿，不能自动投稿。")
        return
    event.stop_event()
    if str(event.get_sender_id()) != plugin.owner:
        yield event.plain_result("只有主人可以审核和投稿大肥鱼的草稿。")
        return
    if plugin.lock.locked():
        yield event.plain_result("我正在处理上一批草稿，完成后再发这条指令就好。")
        return
    async with plugin.lock:
        draft = None
        record = ledger[str(draft_id)]
        fallback_normal = plugin.config.get("quota_fallback_normal", True)
        try:
            metadata = plugin.context.get_registered_star("astrbot_plugin_qzone_ultra")
            if metadata is None or not metadata.activated:
                raise ContributionError("空间插件暂不可用")
            qzone = metadata.star_cls
            draft = await qzone.drafts.get_async(draft_id)
            if draft is None or str(draft.author_uin) != plugin.owner:
                raise ContributionError("找不到属于主人的待审草稿")
            if draft.status not in ("pending", "published"):
                raise ContributionError("该稿已拒绝或撤回，不能发表")
            check_reviewed_content(draft, record)
            client = qzone._capture_onebot_sender(event)
            if client is None:
                raise ContributionError("QQ 连接暂不可用")
            native = NativeContribution(
                client.call_action, str(plugin.config.get("bot_qq", "100000002"))
            )
            await native.check_account()
            newly_published = False
            if draft.status == "pending":
                if action != "过稿" and action not in ("通过稿件", "通过投稿"):
                    yield event.plain_result(
                        f"稿件 #{draft_id} 还没通过审核。选中后发 /过稿 {draft_id} 才发表和投稿。"
                    )
                    return
                quota_exhausted = await native.quota() <= 0
                if quota_exhausted and not fallback_normal:
                    raise QuotaExhausted(
                        "今天的空友投稿额度已用完，草稿保留待审，明天再过稿即可"
                    )
                yield event.plain_result(
                    f"空友爱看额度已用完，正在由大肥鱼把你审核的 #{draft_id} 发表到普通 QQ 空间。"
                    if quota_exhausted
                    else f"正在由大肥鱼发表你审核的 #{draft_id}，并自动投稿到空友爱看。"
                )
                original_results = [
                    result async for result in qzone.approve_post(event)
                ]
                draft = await qzone.drafts.get_async(draft_id)
                if draft.status != "published" or not draft.published_fid:
                    for result in original_results:
                        yield result
                    return
                newly_published = True
                record["published_fid"] = draft.published_fid
                if quota_exhausted:
                    mark_ordinary_publication(path, ledger, record)
                    yield event.plain_result(ordinary_publication_message(draft_id))
                    return
                record["contribution_state"] = "published"
                save_ledger(path, ledger)
            if not draft.published_fid:
                raise ContributionError("原说说编号尚未保存，已停止，避免重复发表")
            row = None
            for attempt in range(3):
                try:
                    row = await native.find_feed(draft.published_fid)
                    break
                except ContributionError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1)
            status = native.feed_status(row)
            if status in REVIEW_STATES:
                record["contribution_state"] = "confirmed"
                record["platform_status"] = status
                save_ledger(path, ledger)
                yield event.plain_result(
                    f"稿件 #{draft_id} 已由大肥鱼发表并投稿，当前：{REVIEW_STATES[status]}。"
                )
                return
            if action == "投稿状态" or (
                not newly_published
                and action != "补投稿"
                and record.get("contribution_state")
                in ("attempted", "unknown", "accepted", "confirmed", "ordinary_only")
            ):
                state = record.get("contribution_state")
                if state == "ordinary_only":
                    yield event.plain_result(ordinary_publication_message(draft_id))
                    return
                text = (
                    "投稿请求已被平台接受，审核状态尚未同步"
                    if state in ("accepted", "confirmed")
                    else "说说已发表，空友投稿尚未确认"
                )
                yield event.plain_result(
                    f"稿件 #{draft_id}：{text}。需要补投时发 /补投稿 {draft_id}，不会重新发表说说。"
                )
                return
            # 校验发表正文仍对应审核稿，不使用相似文本去猜测动态身份。
            if row.get("content", "").strip() != draft.content.strip():
                raise ContributionError("平台返回的正文与审核稿不一致，已停止自动投稿")
            record["contribution_state"] = "attempted"
            record["contribution_attempted_at"] = datetime.now(UTC).isoformat()
            save_ledger(path, ledger)
            await native.submit(row)
            record["contribution_state"] = "accepted"
            record["contribution_accepted_at"] = datetime.now(UTC).isoformat()
            save_ledger(path, ledger)
            for attempt in range(3):
                row = await native.find_feed(draft.published_fid)
                status = native.feed_status(row)
                if status in REVIEW_STATES:
                    record["contribution_state"] = "confirmed"
                    record["platform_status"] = status
                    save_ledger(path, ledger)
                    break
                if attempt < 2:
                    await asyncio.sleep(1)
            detail = REVIEW_STATES.get(status, "投稿请求已被平台接受，审核状态尚未同步")
            yield event.plain_result(
                f"稿件 #{draft_id} 已由大肥鱼发表并提交空友爱看。{detail}。你只负责审核，后续由我完成。"
            )
        except Exception as error:  # noqa: BLE001 - 审核边界保留发表阶段，禁止盲目重发。
            if (
                isinstance(error, QuotaExhausted)
                and fallback_normal
                and draft
                and draft.status == "published"
            ):
                mark_ordinary_publication(path, ledger, record)
                yield event.plain_result(ordinary_publication_message(draft_id))
                return
            logger.exception("大肥鱼自动投稿未完成。")
            if record.get("contribution_state") == "attempted":
                record["contribution_state"] = "unknown"
                save_ledger(path, ledger)
            reason = (
                str(error)
                if isinstance(error, ContributionError)
                else "连接或平台响应暂不可确认"
            )
            if draft and draft.status == "published":
                yield event.plain_result(
                    f"稿件 #{draft_id} 的说说已发表，空友投稿还未完成：{reason}。发 /投稿状态 {draft_id} 可查询；发 /补投稿 {draft_id} 只补投原动态，不会重复发表。"
                )
            else:
                yield event.plain_result(f"尚未发表，草稿仍保留：{reason}。")
