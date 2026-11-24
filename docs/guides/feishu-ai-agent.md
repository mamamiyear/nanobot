# Build a Feishu AI Agent with nanobot

This guide connects nanobot to Feishu or Lark through the `feishu` channel. The channel uses a WebSocket long connection, so the first setup does not require a public webhook URL.

## What this guide builds

- a Feishu/Lark bot app connected to nanobot
- the `feishu` channel enabled in `config.json`
- one pairing-approved Feishu or Lark user
- mention-only group behavior for first deployment

## Prerequisites

- A normal reply in your existing nanobot WebUI or CLI. If you have not reached that point, complete [Quick Start](../quick-start.md) first.

- A Feishu or Lark account that can create or approve bot apps.
- Permission to run `nanobot gateway` continuously.

## Continue from your running instance

If you are already chatting in the WebUI, keep it open and continue below. It has already started the gateway. To reopen it later, use the same installation's `nanobot webui` command; there is no need to install nanobot again.

For terminal or server setup, use the manual configuration section below. Reuse the config/home and executable from your working instance. Docker users should use the [container commands](../deployment.md#docker-compose).

## Enable the Feishu channel

Open **Channels → Feishu** and follow the QR connection flow. Install support if prompted, then open the authorization link or scan the code. If using an existing app, enter its App ID and App Secret in the setup panel. Enable the channel, save, and follow any restart prompt.

<details>
<summary>Manual configuration</summary>

Install the optional channel dependency:

```bash
nanobot plugins enable feishu
```

The easiest path is QR login:

```bash
nanobot channels login feishu
```

Open the printed URL or scan the QR code. nanobot writes the generated `appId`, `appSecret`, `domain`, and `enabled` fields into the active config.

In WebUI, open **Channels → Feishu** and choose **Connect** for the first bot, or **Add another assistant** below your existing assistants. Each new assistant has its own settings and sender approvals; adding one does not replace an existing bot. Cancel the QR flow to stop an unfinished authorization.

If QR login is unavailable, create a Feishu/Lark app manually and merge this shape into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "groupPolicy": "mention",
      "streaming": true,
      "domain": "feishu"
    }
  }
}
```

Omitting `allowFrom` enables pairing-only mode. A new user should DM the bot, get a pairing code, and be approved before using the bot normally.

For manual apps, enable the Bot capability, receive-message events, and Long Connection mode. If your app cannot get the `cardkit:card:write` permission, set `"streaming": false`.

</details>

## Apply the settings

In the WebUI, follow any restart prompt and keep the launcher running for the first test. You do not need to start another gateway. For unattended operation afterward, use [background or service mode](../cli-reference.md#gateway).

For manual config changes, restart the existing gateway through its owning terminal, `nanobot gateway restart` for background mode, or its service/container supervisor. If none is running, start `nanobot gateway` and leave it running. Run diagnostic CLI commands in a separate terminal using the same installation and config.

## Test a message

DM the bot first. It should return a pairing code. Return to the WebUI pairing prompt and enter the code from your own private chat. Only a matching pending code is approved; do not enter another person's code. Then send your message again.

<details>
<summary>Terminal-only pairing</summary>

In a separate local terminal, using the same instance:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Replace the example code with your actual code.

</details>

After approval, DM the bot again or mention it in a group chat:

```text
@nanobot Hello from Feishu
```

## Automatic DM topics

In **Channels → Feishu → the selected assistant → Advanced**, enable **Auto-thread direct messages** (单聊自动话题回复). Set `dmReplyInThread: true` on the matching entry in `channels.feishu.instances[]`; legacy single-bot configurations also accept `channels.feishu.dmReplyInThread`. The default is `false`, independently for each assistant. Keep the existing entry's credentials and permissions when merging this setting.

After installing a version that includes this setting, run `nanobot onboard --refresh` to add missing fields to every Feishu instance, including disabled instances. Existing values and inherited settings are preserved. New configurations contain a default entry in `channels.feishu.instances[]` with `dmReplyInThread: false`; existing flat single-bot configurations retain their format. Onboarding does not upgrade the installed program.

Each ordinary top-level private message opens a native topic without an @mention. Follow-ups share the root message's session; another top-level question gets a separate session. Top-level commands such as `/new` do not open topics. This does not require `replyToMessage`; group `replyToMessage`, `topicIsolation`, and sender approval are unchanged. Text, split cards, attachments, streaming cards, and ordinary replies after a streaming failure use the same topic.

The adapter uses the [Reply Message API](https://open.feishu.cn/document/server-docs/im-v1/message/reply?lang=zh-CN) with `reply_in_thread=true`. Explicit unsupported-topic errors (`230071`, `230072`) are logged and downgraded to an ordinary reply, not reported as topic creation. If a follow-up only supplies `thread_id`, the adapter resolves its root through [topic history](https://open.feishu.cn/document/server-docs/im-v1/message/list); the app needs a message-read scope such as `im:message:readonly`. If that lookup fails, a warning is logged and the topic remains isolated, but the original session context cannot be restored for that turn.

## Security notes

- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a static allowlist.
- Keep `groupPolicy` as `"mention"` before inviting the bot into busy groups.
- Store app secrets through environment variables for deployed services.
- Review file, shell, and web tool access before adding more users.

## Troubleshooting

- If QR login is unavailable, use manual app setup from the full chat-apps reference.
- If streaming cards fail, confirm `cardkit:card:write` or set `"streaming": false`.
- If no messages arrive, check Feishu/Lark event permissions, Long Connection mode, and `nanobot gateway --verbose`.
- If a first DM returns a pairing code, approve it before testing normal replies.
- If WebUI cannot approve a pending code, check the reported error and select **Retry**. You do not need another code while the current one is valid.
- If WebUI reports that the pairing code could not be sent, the DM reached nanobot but its reply failed. Check the gateway log for the Feishu error and request ID, check that the app has permission to send messages as a bot (`im:message:send_as_bot`), and publish any permission changes. Then send another private message to retry; nanobot reuses the unexpired code. Pairing replies use plain text and do not need streaming-card permissions.
- If neither a code nor a pairing request appears, check the running gateway, the app's receive-message subscription, and which assistant you messaged. A saved App ID and App Secret mean **Configured**, not that message delivery has been tested. Do not set `allowFrom` to `*` to work around pairing failures.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [AI Agent Memory](./ai-agent-memory.md)
- [Configure MCP tools](./configure-mcp-tools.md)
