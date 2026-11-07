"""验证主人权限、群聊隔离、失败保稿及真实待审稿库的兼容性。"""

import hashlib
import importlib.util
import json
import logging
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

PLUGIN_DIR = Path(__file__).resolve().parents[1]
RUNTIME = PLUGIN_DIR.parents[1]
base_plugin = os.environ.get("QZONE_PLUGIN_DIR")
if base_plugin:
    sys.path.insert(0, base_plugin)
from qzone_bridge.drafts import DraftStore


def decorator(*args, **kwargs):
    return lambda function: function


class Star:
    def __init__(self, context):
        self.context = context


modules = {
    name: types.ModuleType(name)
    for name in (
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.api.provider",
        "astrbot.api.star",
    )
}
modules["astrbot.api"].logger = logging.getLogger("draft_test")
modules["astrbot.api.event"].AstrMessageEvent = object
modules["astrbot.api.event"].filter = types.SimpleNamespace(
    on_astrbot_loaded=decorator,
    on_llm_request=decorator,
    permission_type=decorator,
    command=decorator,
    llm_tool=decorator,
    event_message_type=decorator,
    EventMessageType=types.SimpleNamespace(ALL="all"),
    PermissionType=types.SimpleNamespace(ADMIN="admin"),
)
modules["astrbot.api.provider"].ProviderRequest = object
modules["astrbot.api.star"].Context = object
modules["astrbot.api.star"].Star = Star
modules["astrbot.api.star"].StarTools = types.SimpleNamespace(
    get_data_dir=lambda _: Path(tempfile.gettempdir())
)
modules["astrbot.api.star"].register = decorator
with patch.dict(sys.modules, modules):
    spec = importlib.util.spec_from_file_location(
        "fish_draft_test",
        PLUGIN_DIR / "main.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    plugin_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = plugin_module
    spec.loader.exec_module(plugin_module)
    parse_pictures = sys.modules["fish_draft_test.pictures"].parse_pictures
    review_module = sys.modules["fish_draft_test.review"]
    native_module = sys.modules["fish_draft_test.contribution"]


OWNER = "100000001"
SOURCES = [
    {
        "title": "真实来源",
        "summary": "海洋小知识",
        "url": "https://example.org/ocean",
        "query": "海洋",
    }
]
CANDIDATES = [
    {
        "text": f"本鱼今天看了点海洋小知识，想把自己的小日子过得更有意思。第{i}个脑洞是先舒舒服服地冒个泡。",
        "source_ids": [1],
    }
    for i in range(3)
]


class ReviewFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = DraftStore(self.folder / "drafts.json")
        self.sender = types.SimpleNamespace(send_private_msg=AsyncMock())
        # 不提供任何发表方法，生成路径若试图发表就会失败。
        self.qzone = types.SimpleNamespace(
            drafts=self.store, _capture_onebot_sender=lambda _: self.sender
        )
        self.provider = types.SimpleNamespace(
            text_chat=AsyncMock(
                return_value=types.SimpleNamespace(
                    completion_text=json.dumps({"drafts": CANDIDATES})
                )
            )
        )
        self.context = types.SimpleNamespace(
            get_registered_star=lambda _: types.SimpleNamespace(
                activated=True, star_cls=self.qzone
            ),
            get_using_provider_async=AsyncMock(return_value=self.provider),
            persona_manager=types.SimpleNamespace(
                get_default_persona_v3=AsyncMock(
                    return_value={"prompt": "这是原有大肥鱼人格"}
                )
            ),
            deactivate_llm_tool_async=AsyncMock(),
        )
        self.plugin = plugin_module.FishQzoneDrafts(
            self.context,
            {"owner_qq": OWNER, "search_queries": ["日常趣事"], "with_images": False},
        )
        self.plugin.data_dir = self.folder / "sources"
        self.search = AsyncMock(return_value=SOURCES)
        self.search_patch = patch.object(plugin_module, "search_sources", self.search)
        self.search_patch.start()
        self.addCleanup(self.search_patch.stop)

    def event(self, sender=OWNER):
        return types.SimpleNamespace(
            get_sender_id=lambda: sender,
            unified_msg_origin="qq:GroupMessage:123456",
        )

    async def test_non_owner_cannot_search_generate_save_or_send(self):
        result = await self.plugin.tool_drafts(self.event("12345"))
        self.assertIn("只有主人", result)
        self.search.assert_not_awaited()
        self.provider.text_chat.assert_not_awaited()
        self.sender.send_private_msg.assert_not_awaited()
        self.assertEqual(await self.store.list_async(), [])

    async def test_group_trigger_creates_three_pending_drafts_and_only_privately_sends_owner(
        self,
    ):
        result = await self.plugin.make_drafts(self.event())
        self.assertIn("已私发", result)
        rows = await self.store.list_async()
        self.assertEqual(len(rows), 3)
        self.assertEqual({row.status for row in rows}, {"pending"})
        self.assertEqual({row.group_id for row in rows}, {0})
        self.assertEqual({row.author_uin for row in rows}, {int(OWNER)})
        args = self.provider.text_chat.await_args.kwargs
        self.assertIsNone(args["func_tool"])
        self.assertEqual(args["contexts"], [])
        self.assertIn("这是原有大肥鱼人格", args["system_prompt"])
        notification = self.sender.send_private_msg.await_args.kwargs
        self.assertEqual(notification["user_id"], int(OWNER))
        ledger = json.loads(
            (self.plugin.data_dir / "sources.json").read_text(encoding="utf-8")
        )
        for row in rows:
            self.assertIn(row.content, notification["message"])
            self.assertNotIn("example.org", row.content)
            self.assertEqual(
                ledger[str(row.id)]["sha256"],
                hashlib.sha256(row.content.encode()).hexdigest(),
            )

    async def test_search_failure_does_not_invent_sources_or_create_drafts(self):
        self.search.return_value = []
        self.assertIn("没能取得", await self.plugin.make_drafts(self.event()))
        self.provider.text_chat.assert_not_awaited()
        self.assertEqual(await self.store.list_async(), [])

    async def test_picture_preview_and_persistent_publish_attachments_are_the_same_files(
        self,
    ):
        pictures = []
        for index in range(3):
            path = self.folder / f"picture{index}.jpg"
            path.write_bytes(b"fixture")
            pictures.append(
                dict(
                    SOURCES[0],
                    image_path=str(path.resolve()),
                    image_size=7,
                    image_sha256="fixture",
                )
            )
        candidates = [
            dict(item, source_ids=[index]) for index, item in enumerate(CANDIDATES, 1)
        ]
        self.provider.text_chat.return_value.completion_text = json.dumps(
            {"drafts": candidates}
        )
        self.plugin.config["with_images"] = True
        with patch.object(
            plugin_module, "find_pictures", AsyncMock(return_value=pictures)
        ):
            await self.plugin.make_drafts(self.event())
        self.search.assert_not_awaited()
        rows = await self.store.list_async()
        self.assertEqual(len(rows), 3)
        self.assertEqual(self.sender.send_private_msg.await_count, 3)
        for row, notification, picture in zip(
            rows, self.sender.send_private_msg.await_args_list, pictures
        ):
            source = Path(picture["image_path"]).as_uri()
            self.assertEqual(row.status, "pending")
            self.assertEqual(row.media[0]["source"], source)
            self.assertEqual(notification.kwargs["user_id"], int(OWNER))
            self.assertEqual(notification.kwargs["message"][1]["data"]["file"], source)
            self.assertIn(
                row.content, notification.kwargs["message"][0]["data"]["text"]
            )
        self.assertIn(
            "不科普", self.provider.text_chat.await_args.kwargs["system_prompt"]
        )
        self.assertNotIn(
            str(self.folder), self.provider.text_chat.await_args.kwargs["prompt"]
        )

    async def test_incomplete_picture_search_does_not_generate_a_silent_text_only_draft(
        self,
    ):
        self.plugin.config["with_images"] = True
        with patch.object(
            plugin_module, "find_pictures", AsyncMock(return_value=[SOURCES[0]])
        ):
            result = await self.plugin.make_drafts(self.event())
        self.assertIn("没能找齐", result)
        self.provider.text_chat.assert_not_awaited()
        self.assertEqual(await self.store.list_async(), [])

    def test_picture_search_rejects_arbitrary_download_hosts_and_stock_watermarks(self):
        import html

        item = {
            "t": "困困小猫",
            "purl": "https://example.org/cat",
            "turl": "https://ts3.mm.bing.net/th?id=OIP.abc123&redirect=http://127.0.0.1",
        }

        def page(data):
            return '<a m="' + html.escape(json.dumps(data), quote=True) + '">'

        parsed = parse_pictures(page(item), "猫咪")
        self.assertEqual(len(parsed), 1)
        self.assertNotIn("redirect", parsed[0]["thumbnail"])
        self.assertEqual(
            parse_pictures(page(dict(item, t="三角洲行动地图攻略")), "猫咪"), []
        )
        for thumbnail in (
            "http://127.0.0.1/th?id=OIP.abc123",
            "https://evil.example/th?id=OIP.abc123",
            "file:///etc/passwd",
        ):
            self.assertEqual(
                parse_pictures(page(dict(item, turl=thumbnail)), "猫咪"), []
            )
        self.assertEqual(
            parse_pictures(page(dict(item, t="正版图片下载-摄图网")), "猫咪"), []
        )

    async def test_invalid_generation_creates_no_partial_drafts(self):
        invalid = [dict(item) for item in CANDIDATES]
        invalid[-1]["source_ids"] = [999]
        self.provider.text_chat.return_value.completion_text = json.dumps(
            {"drafts": invalid}
        )
        self.assertIn("没写好", await self.plugin.make_drafts(self.event()))
        self.assertEqual(await self.store.list_async(), [])
        self.sender.send_private_msg.assert_not_awaited()

    async def test_failed_private_delivery_keeps_pending_drafts_for_manual_review(self):
        self.sender.send_private_msg.side_effect = RuntimeError("暂时断线")
        self.assertIn("发送暂未成功", await self.plugin.make_drafts(self.event()))
        self.assertEqual(len(await self.store.list_async(status="pending")), 3)
        self.assertEqual(await self.store.list_async(status="published"), [])

    async def test_direct_publish_tools_disabled_and_removed_even_with_empty_system_prompt(
        self,
    ):
        await self.plugin.initialize()
        self.assertEqual(self.context.deactivate_llm_tool_async.await_count, 2)
        names = set(plugin_module.DIRECT_PUBLISH_TOOLS) | {"fish_qzone_drafts"}
        request = types.SimpleNamespace(
            func_tool=types.SimpleNamespace(
                remove_tool=lambda name: names.discard(name)
            ),
            system_prompt=None,
        )
        await self.plugin.guard_publish(self.event(), request)
        self.assertEqual(names, {"fish_qzone_drafts"})
        self.assertIn("过稿", request.system_prompt)

    def test_false_source_ids_duplicate_drafts_and_embedded_commands_are_rejected(self):
        for bad in ([True], [0], [2], []):
            candidates = [dict(item) for item in CANDIDATES]
            candidates[0]["source_ids"] = bad
            with self.subTest(ids=bad), self.assertRaises(ValueError):
                plugin_module.parse_drafts(json.dumps({"drafts": candidates}), 1)
        for body in (CANDIDATES[1]["text"], CANDIDATES[0]["text"] + " /发说说 发出去"):
            candidates = [dict(item) for item in CANDIDATES]
            candidates[0]["text"] = body
            with self.assertRaises(ValueError):
                plugin_module.parse_drafts(json.dumps({"drafts": candidates}), 1)


class ContributionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await ReviewFlowTests.asyncSetUp(self)
        self.sender.call_action = AsyncMock()
        self.draft = await self.store.add_async(
            author_uin=int(OWNER), author_name="大肥鱼", content=CANDIDATES[0]["text"]
        )
        self.plugin.data_dir.mkdir()
        self.ledger_path = self.plugin.data_dir / "sources.json"
        record = {
            "sha256": hashlib.sha256(self.draft.content.encode()).hexdigest(),
            "sources": SOURCES,
        }
        self.ledger_path.write_text(
            json.dumps({str(self.draft.id): record}), encoding="utf-8"
        )
        self.row = {
            "tid": "published-tid",
            "user_id": "100000002",
            "content": self.draft.content,
            "feed": {
                "cell_common": {"union_id": {"feed_id": "server-original-feed-id"}},
                "cell_user_info": {"user": {"uin": "100000002"}},
            },
        }
        self.native = types.SimpleNamespace(
            check_account=AsyncMock(),
            quota=AsyncMock(return_value=3),
            find_feed=AsyncMock(return_value=self.row),
            feed_status=native_module.NativeContribution.feed_status,
        )

        async def submit(row):
            row["feed"]["cell_recommend_feed"] = {
                "archivable_status": {"archivable_info": {"value": 101}}
            }

        self.native.submit = AsyncMock(side_effect=submit)
        self.publish_count = 0

        async def approve(event):
            self.publish_count += 1

            def update(current):
                current.status = "published"
                current.published_fid = "published-tid"

            await self.store.update_async(self.draft.id, update)
            yield "基础插件已发表"

        self.qzone.approve_post = approve
        native_patch = patch.object(
            review_module, "NativeContribution", return_value=self.native
        )
        native_patch.start()
        self.addCleanup(native_patch.stop)
        logging_patch = patch.object(review_module, "logger", Mock())
        logging_patch.start()
        self.addCleanup(logging_patch.stop)

    def review_event(self, action="过稿", sender=OWNER):
        return types.SimpleNamespace(
            get_sender_id=lambda: sender,
            get_message_str=lambda: f"/{action} {self.draft.id}",
            stop_event=Mock(),
            plain_result=lambda text: text,
        )

    async def run_review(self, action="过稿", sender=OWNER):
        return [
            item
            async for item in review_module.review_message(
                self.plugin, self.review_event(action, sender)
            )
        ]

    async def test_approved_draft_publishes_then_submits_and_confirms_platform_review(
        self,
    ):
        messages = await self.run_review()
        self.assertIn("平台审核中", messages[-1])
        self.assertEqual(self.publish_count, 1)
        self.native.submit.assert_awaited_once()
        row = await self.store.get_async(self.draft.id)
        self.assertEqual(row.status, "published")
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(ledger[str(self.draft.id)]["contribution_state"], "confirmed")
        await self.run_review()
        self.assertEqual(self.publish_count, 1)
        self.native.submit.assert_awaited_once()

    async def test_non_owner_cannot_approve_or_submit(self):
        messages = await self.run_review(sender="12345")
        self.assertIn("只有主人", messages[-1])
        self.assertEqual(self.publish_count, 0)
        self.native.check_account.assert_not_awaited()
        self.native.submit.assert_not_awaited()

    async def test_handler_finishes_approval_after_stopping_event_propagation(self):
        event = self.review_event()
        event.send = AsyncMock()
        await self.plugin.review_and_contribute(event)
        event.stop_event.assert_called_once()
        self.assertEqual(self.publish_count, 1)
        self.native.submit.assert_awaited_once()
        self.assertIn("平台审核中", event.send.await_args.args[0])

    async def test_empty_quota_keeps_pending_draft_without_ordinary_publication(self):
        self.plugin.config["quota_fallback_normal"] = False
        self.native.quota.return_value = 0
        self.assertIn("额度已用完", (await self.run_review())[-1])
        self.assertEqual(self.publish_count, 0)
        self.assertEqual((await self.store.get_async(self.draft.id)).status, "pending")
        self.native.submit.assert_not_awaited()

    async def test_empty_quota_defaults_to_one_ordinary_publication_without_submission(
        self,
    ):
        self.native.quota.return_value = 0
        messages = await self.run_review()
        self.assertIn("普通 QQ 空间", messages[-1])
        self.assertIn("本条未投稿", messages[-1])
        self.assertEqual(self.publish_count, 1)
        draft = await self.store.get_async(self.draft.id)
        self.assertEqual(draft.status, "published")
        self.assertEqual(draft.published_fid, "published-tid")
        record = json.loads(self.ledger_path.read_text(encoding="utf-8"))[
            str(self.draft.id)
        ]
        self.assertEqual(record["contribution_state"], "ordinary_only")
        self.assertEqual(record["ordinary_reason"], "quota_exhausted")
        self.assertEqual(record["published_fid"], "published-tid")
        self.native.submit.assert_not_awaited()
        self.native.find_feed.assert_not_awaited()

    async def test_ordinary_post_is_not_submitted_by_reapproval_or_status_after_quota_returns(
        self,
    ):
        self.native.quota.return_value = 0
        await self.run_review()
        self.native.quota.return_value = 3
        for action in ("过稿", "投稿状态", "通过稿件", "通过投稿"):
            self.assertIn("本条未投稿", (await self.run_review(action))[-1])
        self.assertEqual(self.publish_count, 1)
        self.native.submit.assert_not_awaited()

    async def test_explicit_retry_of_ordinary_post_submits_original_without_republishing(
        self,
    ):
        self.native.quota.return_value = 0
        await self.run_review()
        self.native.quota.return_value = 3
        self.assertIn("平台审核中", (await self.run_review("补投稿"))[-1])
        self.assertEqual(self.publish_count, 1)
        self.native.submit.assert_awaited_once_with(self.row)
        self.assertEqual(
            json.loads(self.ledger_path.read_text(encoding="utf-8"))[
                str(self.draft.id)
            ]["contribution_state"],
            "confirmed",
        )

    async def test_unconfirmed_quota_does_not_trigger_ordinary_publication(self):
        self.native.quota.side_effect = TimeoutError()
        self.assertIn("尚未发表", (await self.run_review())[-1])
        self.assertEqual(self.publish_count, 0)
        self.assertEqual((await self.store.get_async(self.draft.id)).status, "pending")
        self.native.submit.assert_not_awaited()

    async def test_quota_exhausted_between_publication_and_submission_keeps_ordinary_post(
        self,
    ):
        self.native.submit.side_effect = native_module.QuotaExhausted("额度已用完")
        self.assertIn("本条未投稿", (await self.run_review())[-1])
        self.assertEqual(self.publish_count, 1)
        self.assertEqual(
            json.loads(self.ledger_path.read_text(encoding="utf-8"))[
                str(self.draft.id)
            ]["contribution_state"],
            "ordinary_only",
        )
        await self.run_review()
        self.assertEqual(self.publish_count, 1)
        self.native.submit.assert_awaited_once()

    async def test_explicit_retry_with_still_empty_quota_keeps_same_ordinary_post(self):
        self.native.quota.return_value = 0
        await self.run_review()
        self.native.submit.side_effect = native_module.QuotaExhausted("额度已用完")
        self.assertIn("本条未投稿", (await self.run_review("补投稿"))[-1])
        self.assertEqual(self.publish_count, 1)
        self.native.submit.assert_awaited_once()

    async def test_native_empty_quota_raises_specific_error_before_sending_submission(
        self,
    ):
        query_response = native_module.data(4, native_module.integer(1, 0)).hex()
        call = AsyncMock(return_value=query_response)
        native = native_module.NativeContribution(call, "100000002")
        with self.assertRaises(native_module.QuotaExhausted):
            await native.submit(self.row)
        call.assert_awaited_once()
        self.assertEqual(call.await_args.kwargs["cmd"], native_module.QUERY)

    async def test_changed_body_is_not_published(self):
        def change(current):
            current.content += "修改后的内容"

        await self.store.update_async(self.draft.id, change)
        self.assertIn("正文已变化", (await self.run_review())[-1])
        self.assertEqual(self.publish_count, 0)

    async def test_submission_timeout_never_republishes_and_only_explicit_retry_resubmits(
        self,
    ):
        self.native.submit.side_effect = TimeoutError()
        messages = await self.run_review()
        self.assertIn("说说已发表", messages[-1])
        self.assertEqual(self.publish_count, 1)
        self.assertEqual(
            json.loads(self.ledger_path.read_text(encoding="utf-8"))[
                str(self.draft.id)
            ]["contribution_state"],
            "unknown",
        )
        await self.run_review()
        self.assertEqual(self.native.submit.await_count, 1)
        self.assertEqual(self.publish_count, 1)
        await self.run_review("补投稿")
        self.assertEqual(self.native.submit.await_count, 2)
        self.assertEqual(self.publish_count, 1)

    async def test_status_and_retry_commands_cannot_approve_a_pending_draft(self):
        for action in ("补投稿", "投稿状态"):
            self.assertIn("还没通过审核", (await self.run_review(action))[-1])
        self.assertEqual(self.publish_count, 0)
        self.native.submit.assert_not_awaited()

    async def test_native_query_unwraps_real_qq_response_as_three_remaining_submissions(
        self,
    ):
        call = AsyncMock(return_value="080122020803")
        native = native_module.NativeContribution(call, "100000002")
        self.assertEqual(await native.quota(), 3)
        request = native_module.decode(bytes.fromhex(call.await_args.kwargs["data"]))
        body = native_module.decode(native_module.first(request, 4))
        self.assertEqual(native_module.first(body, 2), 1)

    async def test_native_feed_lookup_rejects_another_accounts_post(self):
        row = dict(self.row, user_id="12345")
        call = AsyncMock(return_value={"msglist": [row]})
        native = native_module.NativeContribution(call, "100000002")
        with self.assertRaises(native_module.ContributionError):
            await native.find_feed("published-tid")

    async def test_native_submission_uses_exact_official_status_and_server_feed_id(
        self,
    ):
        query_response = native_module.data(4, native_module.integer(1, 3)).hex()
        success_response = native_module.data(4, b"").hex()
        call = AsyncMock(side_effect=[query_response, success_response])
        native = native_module.NativeContribution(call, "100000002")
        await native.submit(self.row)
        envelope = native_module.decode(bytes.fromhex(call.await_args.kwargs["data"]))
        request = native_module.decode(native_module.first(envelope, 4))
        self.assertEqual(native_module.first(request, 1), b"server-original-feed-id")
        self.assertEqual(native_module.first(request, 3), b"100000002")
        status = native_module.decode(native_module.first(request, 2))
        self.assertEqual(native_module.first(status, 1), 19)
        self.assertEqual(native_module.first(status, 2), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
