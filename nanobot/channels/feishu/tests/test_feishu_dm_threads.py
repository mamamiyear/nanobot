"""DM topic routing through mocked Feishu APIs, without platform credentials."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("lark_oapi")

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu.runtime import FeishuChannel, FeishuConfig


def _response(*, code=0, msg="ok", **data):
    return SimpleNamespace(
        success=lambda: code == 0, code=code, msg=msg,
        get_log_id=lambda: "test-log", data=SimpleNamespace(**data),
    )


def _channel(**config) -> FeishuChannel:
    channel = FeishuChannel(
        FeishuConfig(enabled=True, allow_from=["*"], **config), MessageBus(),
    )
    channel._running = True
    channel._client = MagicMock()
    channel._add_reaction = AsyncMock(return_value=None)
    channel._get_message_content_sync = MagicMock(return_value=None)
    # A successful reply is deliberately allowed to omit thread_id.
    channel._client.im.v1.message.reply.return_value = _response(message_id="om_reply")
    channel._client.im.v1.message.create.return_value = _response(message_id="om_create")
    channel._client.cardkit.v1.card.create.return_value = _response(card_id="card_1")
    channel._client.cardkit.v1.card_element.content.return_value = _response()
    channel._client.cardkit.v1.card.settings.return_value = _response()
    return channel


async def _receive(channel, message_id="om_root", *, text="hello", **fields):
    message = SimpleNamespace(
        message_id=message_id, message_type="text", content=json.dumps({"text": text}),
        **{"chat_id": "oc_dm", "chat_type": "p2p", "mentions": [], **fields},
    )
    await channel._on_message(SimpleNamespace(event=SimpleNamespace(
        message=message,
        sender=SimpleNamespace(sender_type="user", sender_id=SimpleNamespace(open_id="ou_user")),
    )))
    assert channel.bus.inbound_size == 1
    return await channel.bus.consume_inbound()


async def _answer(channel, inbound, content="answer", **kwargs):
    await channel.send(OutboundMessage(
        channel=channel.name, chat_id=inbound.chat_id, content=content,
        metadata=inbound.metadata, **kwargs,
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"dm_reply_in_thread": False}, {"dm_reply_in_thread": True}])
async def test_dm_first_question_and_root_followup(config):
    channel = _channel(**config)
    first = await _receive(channel)
    await _answer(channel, first)
    followup = await _receive(channel, "om_followup", root_id="om_root")
    other = await _receive(channel, "om_other")
    if config.get("dm_reply_in_thread"):
        assert first.session_key == followup.session_key == "feishu:oc_dm:om_root"
        assert other.session_key == "feishu:oc_dm:om_other"
        await _answer(channel, followup)
        requests = [call.args[0] for call in channel._client.im.v1.message.reply.call_args_list]
        assert [req.message_id for req in requests] == ["om_root", "om_root"]
        assert all(req.request_body.reply_in_thread is True for req in requests)
        channel._client.im.v1.message.create.assert_not_called()
    else:
        assert first.session_key == followup.session_key == other.session_key == "feishu:ou_user"
        channel._client.im.v1.message.create.assert_called_once()
        channel._client.im.v1.message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_thread_only_followup_resolves_root_even_without_reply_response_thread_id():
    channel = _channel(dm_reply_in_thread=True)
    first = await _receive(channel)
    await _answer(channel, first)
    channel._client.im.v1.message.list.return_value = _response(items=[
        SimpleNamespace(message_id="om_reply", root_id="om_root", chat_id="oc_dm"),
    ])
    followup = await _receive(channel, "om_followup", thread_id="omt_topic")
    assert followup.session_key == first.session_key
    request = channel._client.im.v1.message.list.call_args.args[0]
    assert request.container_id_type == "thread"
    assert request.container_id == "omt_topic"
    assert request.sort_type == "ByCreateTimeAsc"
    assert request.page_size == 1
    again = await _receive(channel, "om_followup2", thread_id="omt_topic")
    assert again.session_key == first.session_key
    channel._client.im.v1.message.list.assert_called_once()
    await _answer(channel, followup)
    assert channel._client.im.v1.message.reply.call_args.args[0].message_id == "om_root"


@pytest.mark.asyncio
async def test_thread_aliases_are_scoped_to_chat_and_instance_and_survive_cache_misses():
    channel = _channel(dm_reply_in_thread=True)
    channel.name = "feishu.support"
    first = await _receive(channel, "om_child", root_id="om_root", thread_id="omt_topic")
    assert first.session_key == "feishu.support:oc_dm:om_root"
    cached = await _receive(channel, "om_child2", thread_id="omt_topic")
    assert cached.session_key == first.session_key
    channel._client.im.v1.message.list.assert_not_called()

    channel._client.im.v1.message.list.return_value = _response(items=[
        SimpleNamespace(message_id="om_other_root", root_id=None, chat_id="oc_other"),
    ])
    other_chat = await _receive(channel, "om_child3", chat_id="oc_other", thread_id="omt_topic")
    assert other_chat.session_key == "feishu.support:oc_other:om_other_root"

    restarted = _channel(dm_reply_in_thread=True)
    restarted.name = channel.name
    restarted._client.im.v1.message.list.return_value = _response(items=[
        SimpleNamespace(message_id="om_root", root_id=None, chat_id="oc_dm"),
    ])
    recovered = await _receive(restarted, "om_child4", thread_id="omt_topic")
    assert recovered.session_key == first.session_key
    restarted._client.im.v1.message.list.assert_called_once()

    other_bot = _channel(dm_reply_in_thread=True)
    other_bot.name = "feishu.product"
    other_bot._client.im.v1.message.list.return_value = _response(items=[
        SimpleNamespace(message_id="om_product_root", root_id=None, chat_id="oc_dm"),
    ])
    isolated = await _receive(other_bot, "om_child5", thread_id="omt_topic")
    assert isolated.session_key == "feishu.product:oc_dm:om_product_root"


@pytest.mark.asyncio
async def test_unavailable_root_keeps_followups_in_one_isolated_topic():
    channel = _channel(dm_reply_in_thread=True)
    channel._client.im.v1.message.list.return_value = _response(code=230027, msg="Missing read scope")
    first = await _receive(channel, "om_child1", thread_id="omt_topic")
    second = await _receive(channel, "om_child2", thread_id="omt_topic")
    assert first.session_key == second.session_key == "feishu:oc_dm:omt_topic"
    await _answer(channel, second)
    assert channel._client.im.v1.message.reply.call_args.args[0].message_id == "om_child2"


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/new", "/help"])
async def test_top_level_dm_commands_do_not_open_topics(command):
    channel = _channel(dm_reply_in_thread=True)
    inbound = await _receive(channel, text=command)
    assert inbound.session_key == "feishu:ou_user"
    await _answer(channel, inbound)
    channel._client.im.v1.message.reply.assert_not_called()
    assert channel._client.im.v1.message.create.call_count == (2 if command == "/new" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_to_message", [False, True])
@pytest.mark.parametrize("topic_isolation", [False, True])
async def test_dm_switch_preserves_group_reply_and_session_policy(reply_to_message, topic_isolation):
    channel = _channel(
        dm_reply_in_thread=True, group_policy="open",
        reply_to_message=reply_to_message, topic_isolation=topic_isolation,
    )
    inbound = await _receive(channel, chat_type="group")
    assert inbound.session_key == ("feishu:oc_dm:om_root" if topic_isolation else "feishu:oc_dm")
    await _answer(channel, inbound)
    if reply_to_message:
        request = channel._client.im.v1.message.reply.call_args.args[0]
        assert request.request_body.reply_in_thread is True
    else:
        channel._client.im.v1.message.reply.assert_not_called()
        channel._client.im.v1.message.create.assert_called_once()


_TWO_TABLES = "| A |\n| --- |\n| one |\n\nBetween\n\n| B |\n| --- |\n| two |"


@pytest.mark.asyncio
async def test_nonstreaming_dm_attachments_and_split_cards_stay_in_topic(tmp_path):
    channel = _channel(dm_reply_in_thread=True, streaming=False)
    inbound = await _receive(channel)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"test file")
    channel._upload_file_sync = MagicMock(return_value="file_key")
    await _answer(channel, inbound, _TWO_TABLES, media=[str(attachment)])
    requests = [call.args[0] for call in channel._client.im.v1.message.reply.call_args_list]
    assert [req.request_body.msg_type for req in requests] == ["file", "interactive", "interactive"]
    assert all(req.message_id == "om_root" and req.request_body.reply_in_thread is True for req in requests)
    channel._client.im.v1.message.create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "create", "update"])
async def test_streaming_and_plain_fallback_cards_stay_in_topic(failure):
    channel = _channel(dm_reply_in_thread=True)
    inbound = await _receive(channel)
    if failure == "create":
        channel._client.cardkit.v1.card.create.return_value = _response(code=99999)
    await channel.send_delta(inbound.chat_id, _TWO_TABLES, inbound.metadata)
    if failure == "update":
        channel._client.cardkit.v1.card_element.content.return_value = _response(code=99999)
    await channel.send_delta(inbound.chat_id, "", inbound.metadata, stream_end=True)
    requests = [call.args[0] for call in channel._client.im.v1.message.reply.call_args_list]
    assert len(requests) == {None: 1, "create": 2, "update": 3}[failure]
    assert all(req.message_id == "om_root" and req.request_body.reply_in_thread is True for req in requests)
    channel._client.im.v1.message.create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("code", [230071, 230072])
async def test_explicit_topic_rejection_downgrades_once_without_losing_or_duplicating_reply(streaming, code):
    channel = _channel(dm_reply_in_thread=True, streaming=streaming)
    channel.logger = MagicMock()
    channel._client.im.v1.message.reply.side_effect = [
        _response(code=code, msg="Reply in thread is not supported"),
        _response(message_id="om_plain_reply"),
    ]
    inbound = await _receive(channel)
    if streaming:
        await channel.send_delta(inbound.chat_id, "answer", inbound.metadata)
        await channel.send_delta(inbound.chat_id, "", inbound.metadata, stream_end=True)
    else:
        await _answer(channel, inbound)
    requests = [call.args[0] for call in channel._client.im.v1.message.reply.call_args_list]
    assert len(requests) == 2
    assert requests[0].request_body.reply_in_thread is True
    assert requests[1].request_body.reply_in_thread is not True
    assert requests[0].request_body.content == requests[1].request_body.content
    channel._client.im.v1.message.create.assert_not_called()
    warning = channel.logger.warning.call_args.args
    assert "no topic created" in warning[0]
    assert code in warning


@pytest.mark.asyncio
async def test_stream_fallback_reports_delivery_failure():
    channel = _channel(dm_reply_in_thread=True)
    inbound = await _receive(channel)
    channel._client.cardkit.v1.card.create.return_value = _response(code=99999)
    await channel.send_delta(inbound.chat_id, "answer", inbound.metadata)
    channel._client.im.v1.message.reply.return_value = _response(code=230071)
    channel._client.im.v1.message.create.return_value = _response(code=230035)
    with pytest.raises(RuntimeError, match="message was not delivered"):
        await channel.send_delta(inbound.chat_id, "", inbound.metadata, stream_end=True)
