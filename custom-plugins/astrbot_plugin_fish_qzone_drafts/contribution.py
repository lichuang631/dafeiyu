"""复用已登录 QQ 的固定原生接口，查询额度并投稿本人动态。"""

import asyncio
import time

QUERY = (
    "QzoneV4Service.trpc.qqappai.qzone_contribute_limiter.QzoneContributeLimiter.Query"
)
SUBMIT = "QzoneV4Service.trpc.qqappai.qzone_archive.FeedStatusService.SetFeedStatus"
REVIEW_STATES = {
    101: "平台审核中",
    102: "平台审核已通过",
    103: "平台未收录",
    104: "平台审核未通过",
    105: "平台审核未通过",
}


class ContributionError(Exception):
    """可向主人说明的投稿错误。"""


class QuotaExhausted(ContributionError):
    """已确认没有投稿额度，尚未发送投稿请求。"""


def varint(number: int) -> bytes:
    result = bytearray()
    while number > 127:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)


def integer(field: int, value: int) -> bytes:
    return varint(field * 8) + varint(value)


def data(field: int, value: bytes | str) -> bytes:
    value = value.encode() if isinstance(value, str) else value
    return varint(field * 8 + 2) + varint(len(value)) + value


def decode(payload: bytes) -> dict:
    """有界读取 protobuf 字段，不执行服务器提供的任何指令。"""
    if len(payload) > 65_536:
        raise ContributionError("投稿响应超过预期大小")
    offset = 0
    result = {}

    def read_varint():
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(payload):
                break
            byte = payload[offset]
            offset += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
        raise ContributionError("投稿响应编码不完整")

    while offset < len(payload):
        tag = read_varint()
        field, wire = tag >> 3, tag & 7
        if not field or len(result) > 128:
            raise ContributionError("投稿响应字段异常")
        if wire == 0:
            value = read_varint()
        elif wire in (1, 2, 5):
            size = read_varint() if wire == 2 else 8 if wire == 1 else 4
            if size > len(payload) - offset:
                raise ContributionError("投稿响应长度异常")
            value = payload[offset : offset + size]
            offset += size
        else:
            raise ContributionError("投稿响应包含不支持的字段")
        result.setdefault(field, []).append(value)
    return result


def first(fields: dict, field: int, default=0):
    return fields.get(field, [default])[0]


def request_envelope(body: bytes) -> bytes:
    # 依据腾讯官方 Android QQ 的 StQWebReq，沿用 QQ 空间的 PC 客户端标识。
    return (
        integer(1, int(time.time() * 1000))
        + data(2, "V1_HT5_QZ_9.9.32_001_IDC_B")
        + data(3, "Desktop QQ")
        + data(4, body)
        + data(10, data(1, "fc-appid") + data(2, "101"))
    )


class NativeContribution:
    def __init__(self, call_action, bot_qq: str):
        self.call_action = call_action
        self.bot_qq = str(bot_qq)

    async def call(self, action: str, **params):
        return await asyncio.wait_for(self.call_action(action, **params), timeout=20)

    async def check_account(self):
        login = await self.call("get_login_info")
        if not isinstance(login, dict) or str(login.get("user_id")) != self.bot_qq:
            raise ContributionError("QQ 登录账号与大肥鱼不一致，已停止发表")

    async def rpc(self, command: str, body: bytes) -> dict:
        if command not in (QUERY, SUBMIT):
            raise ContributionError("不支持的投稿操作")
        response = await self.call(
            "send_packet", cmd=command, data=request_envelope(body).hex(), rsp=True
        )
        if not isinstance(response, str) or len(response) > 131_072:
            raise ContributionError("QQ 没有返回可确认的投稿响应")
        try:
            envelope = decode(bytes.fromhex(response))
        except ValueError as error:
            raise ContributionError("QQ 投稿响应格式异常") from error
        if first(envelope, 2) != 0:
            raise ContributionError("QQ 原生投稿服务拒绝了请求")
        body = first(envelope, 4, None)
        if not isinstance(body, bytes):
            raise ContributionError("QQ 投稿服务未返回业务结果")
        return decode(body)

    async def quota(self, feed_id: str = "") -> int:
        result = await self.rpc(QUERY, integer(1, 0) + integer(2, 1) + data(3, feed_id))
        # Query 返回：1剩余次数、2说明、3业务码、4提示弹窗。
        if first(result, 3) != 0:
            raise ContributionError(
                "平台暂不允许投稿："
                + (first(result, 2, b"").decode(errors="replace")[:100] or "请稍后再试")
            )
        count = first(result, 1)
        if not isinstance(count, int) or not 0 <= count <= 1000:
            raise ContributionError("无法确认今日投稿额度")
        return count

    async def find_feed(self, tid: str) -> dict:
        cursor = None
        for _ in range(3):
            params = {"format": "native", "target_uin": self.bot_qq}
            if cursor:
                params["cursor"] = cursor
            result = await self.call("get_qzone_msg_list", **params)
            for row in result.get("msglist", []):
                if str(row.get("tid")) == tid:
                    feed = row.get("feed", {})
                    if (
                        str(row.get("user_id")) != self.bot_qq
                        or str(
                            feed.get("cell_user_info", {}).get("user", {}).get("uin")
                        )
                        != self.bot_qq
                    ):
                        raise ContributionError("动态不属于大肥鱼，已停止投稿")
                    feed_id = (
                        feed.get("cell_common", {}).get("union_id", {}).get("feed_id")
                    )
                    if not isinstance(feed_id, str) or not 1 <= len(feed_id) <= 8192:
                        raise ContributionError("平台没有返回真实动态标识，稍后再查")
                    return row
            cursor = result.get("next_cursor")
            if not cursor:
                break
        raise ContributionError(
            "刚发表的动态尚未同步，稍后发 /补投稿 编号 即可，无需重新发表"
        )

    @staticmethod
    def feed_status(row: dict) -> int:
        return int(
            row.get("feed", {})
            .get("cell_recommend_feed", {})
            .get("archivable_status", {})
            .get("archivable_info", {})
            .get("value")
            or 0
        )

    async def submit(self, row: dict):
        feed_id = row["feed"]["cell_common"]["union_id"]["feed_id"]
        if self.feed_status(row) in REVIEW_STATES:
            return
        if await self.quota(feed_id) <= 0:
            raise QuotaExhausted("今天的投稿额度已用完，保留原说说明天补投稿即可")
        # 官方投稿按钮：FeedStatus(type=19, intValue=1)，uin 与 operator 均为本人。
        body = (
            data(1, feed_id)
            + data(2, integer(1, 19) + integer(2, 1))
            + data(3, self.bot_qq)
            + data(4, self.bot_qq)
        )
        result = await self.rpc(SUBMIT, body)
        if first(result, 1) != 0:
            message = first(result, 2, b"").decode(errors="replace")[:100]
            raise ContributionError(
                "平台未接受投稿" + ("：" + message if message else "，请稍后查询状态")
            )
