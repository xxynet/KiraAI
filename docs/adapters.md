## Adapter Settings


[QQ](#qq)

[Telegram](#telegram)

[BiliBili](#bilibili)


Be sure to comment out the adapter settings you are not going to use

### QQ

本项目使用 [napcat](https://napneko.github.io/) 与QQ客户端交互，如果需要部署到QQ请先配置 napcat（Shell）

并且在`网络配置`中添加 Websocket 服务器，填写一个 token 并且点击启用

在 `config/adapters.in`中修改 QQ 平台配置

```ini
# 适配器标识符，可以自定义
[qq]
# 是否启用，改为false将不会加载适配器
enabled = true
# 平台标识字段，不要修改
platform = QQ
# 对该账号的描述
desc = main QQ account
# bot的QQ账号
bot_pid = xxxxxx
# 主人QQ账号
owner_pid = xxxxx
# 你创建的Websocket服务器地址
ws_uri = ws://localhost:3001
ws_listen_ip = 0.0.0.0
# Websocket服务器token
ws_token = 
# allow_list or deny_list，根据permission_mode选择设置下面的allow_list或deny_list
permission_mode = allow_list
# bot接收消息的群聊
group_allow_list = 1234567890, 9876543210
# bot接收私聊消息的用户
user_allow_list = 1234567890, 9876543210
# bot不接收消息的群聊
group_deny_list = 1234567890, 9876543210
# bot不接收私聊消息的用户
user_deny_list = 1234567890, 9876543210
# 唤醒关键词，消息中出现时会触发回复
waking_keywords = 
```

### Telegram

Go to `@BotFather`, the official bot for creating bots & create your bot.

Enter `Bot Settings` & turn off `Group Privacy`

Modify telegram adapter settings in `config/adapters.in`

```ini
# adapter uuid
[tg]
# Whether to enable, set to false to prevent loading the adapter
enabled = true
# platform uuid, DO NOT MODIFY
platform = Telegram
# description of this account
desc = telegram account
# bot username
bot_pid = user_name
# bot token
bot_token = your_bot_token
# allow_list or deny_list
permission_mode = allow_list
# from which group(s) bot receives messages
group_allow_list = xxx, xxx
# from which user(s) bot receives messages
user_allow_list = xxx, xxx
# from which group(s) bot doesn't receive messages
group_deny_list = xxx, xxx
# from which user(s) bot doesn't receive messages
user_deny_list = xxx, xxx
```

### BiliBili

You need to [get credential information](https://nemo2011.github.io/bilibili-api/#/get-credential)

```ini
[b2]
enabled = false
platform = BiliBili
desc = BiliBili (an Youtube-like video sharing platform) account
bot_uid = 
# one bvid only
listening_bvid = 
listening_interval = 20
message_process_interval = 5
sessdata = 
bili_jct = 
buvid3 = 
dedeuserid = 
ac_time_value = 
```