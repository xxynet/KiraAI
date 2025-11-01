## Adapter Settings


[QQ](#qq)
[Telegram](#telegram)


### QQ

本项目使用 [napcat](https://napneko.github.io/) 与QQ客户端交互，如果需要部署到QQ请先配置 napcat

并且在`网络配置`中添加 Websocket 服务器，填写一个 token 并且点击启用

在 `config/adapters.in`中修改 QQ 平台配置

```ini
# 适配器标识符，可以自定义
[qq]
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
# bot接收消息的群聊
group_list = 1234567890, 9876543210
# bot接收私聊消息的用户
user_list = 1234567890, 9876543210
```

### Telegram

Go to `@BotFather`, the official bot for creating bots & create your bot.

Enter `Bot Settings` & turn off `Group Privacy`

Modify telegram adapter settings in `config/adapters.in`

```ini
# adapter uuid
[tg]
# platform uuid, DO NOT MODIFY
platform = Telegram
# description of this account
desc = telegram account
# bot username
bot_pid = user_name
# bot token
bot_token = your_bot_token
# from which group(s) bot receives messages
group_list = xxx, xxx
# from which user(s) bot receives messages
user_list = xxx, xxx
```
