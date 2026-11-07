# 大肥鱼 QQ 机器人部署与扩展记录

这是基于 [whyever77/dafeiyu-astrbot](https://github.com/whyever77/dafeiyu-astrbot) 的个人部署资料与定制扩展，整理了从 Windows 本机安装，到云服务器常驻、QQ 空间审核发表、指定声音训练与自动回退的全过程。不是 AstrBot、NapCat 或上游大肥鱼项目的官方发行版。

原部署使用 AstrBot 4.29.4、NapCat 4.18.42、Python 3.12.13；Windows 本地声音使用 RTX 5060 Laptop 8GB、PyTorch 2.7.1 + CUDA 12.8。记录日期为 2026-11-07，版本按实际验证环境保留，不代表最新版本。

## 从哪里开始

1. [完整操作步骤](docs/完整操作步骤.md)：按顺序安装、配置和验收。
2. [本机部署记录](docs/本机部署记录.md)：QQ 扫码、主人权限、DeepSeek、语音和表情包。
3. [云端与空间功能记录](docs/云端与空间功能记录.md)：迁移、内存掉线修复、图文草稿审核及空友投稿。
4. [本地声音与降噪](docs/本地声音与降噪.md)：训练、试听、断网备用与自动恢复。
5. [目录与恢复说明](docs/目录与恢复说明.md)：代码用途、还需自行准备的文件及恢复顺序。

## 已有能力

| 功能 | 行为 |
|---|---|
| 大肥鱼人格 | 使用上游人格；DeepSeek 负责聊天 |
| 全员聊天 | 可私聊；群聊通过 @、引用或名称唤醒 |
| 主人管理 | `/ban @成员`、`/pass @成员`、`/banlist` |
| 表情包 | meme_manager，按情绪配图 |
| 语音 | 60% 语音、40% 文字，长期随机概率 |
| 本地指定声音 | GPT-SoVITS v2ProPlus，净化后短素材训练 |
| 自动备用 | 本地离线时用百炼龙嫱；连接恢复后重新使用本地 |
| QQ 空间 | 按需搜趣图、写三条草稿，只交给主人审核 |
| 空友爱看 | 审核后发表并投稿；额度用完照常发普通空间 |
| 指定声音唱歌 | `/唱歌 歌名 歌手` 自动找歌、换声、混回伴奏并分段 |

本地说话服务、自动恢复、云端调用与按歌名唱歌均已实测。[唱歌插件说明](docs/唱歌插件.md)记录音源限制、安装步骤与验收；《叹云兮》本次实际可用的是60秒公开试听，已完成换声和云端分段取回。

## 代码

- `custom-plugins/astrbot_plugin_fish_qzone_drafts`：空间图文草稿、主人审核、投稿及额度回退，1.2.3。
- `custom-plugins/astrbot_plugin_fish_hybrid_voice`：本地声音优先、云端备用，1.0.1。
- `local-voice`：下载资源、转录校对、训练、试听、降噪及后台连接管理。
- `custom-plugins/astrbot_plugin_fish_singing` 和 `singing`：云端点歌插件及本地分离、歌声转换、混音任务。
- `云端部署`：原部署使用的迁移、启动、插件安装和诊断脚本。
- `persona`：上游 MIT 许可的大肥鱼人格，保留来源声明。

## 使用前必须填写

仓库中的主人 QQ `100000001`、机器人 QQ `100000002`、服务器 `203.0.113.10` 均为占位示例，须统一替换为自己的值。配置参考 `examples`。脚本保存了原环境的目录约定，需先阅读步骤，不是下载后即可直接运行的整机镜像。

API Key、服务器密码、SSH 私钥、QQ 登录数据、Cookie、聊天数据库、录音、训练权重、模型缓存及运行快照均未上传。本仓库无法恢复原账号登录和原声音权重；需在自己的机器上填写密钥、扫码并用自己的素材训练。实际运行目录应与此公开仓库分开。

## 测试

```powershell
# 空间测试需要基础插件中的 qzone_bridge；指向你自行下载的 QQ空间Ultra 源码。
$env:QZONE_PLUGIN_DIR = 'D:\test-deps\astrbot_plugin_qzone_ultra'
python -m unittest discover -s custom-plugins/astrbot_plugin_fish_hybrid_voice/tests -v
python -m unittest discover -s custom-plugins/astrbot_plugin_fish_qzone_drafts/tests -v
python -m unittest discover -s singing/tests -v
```

测试覆盖本地/备用切换、断线恢复、超时、取消、主人审稿权限、重复发表保护、配图校验和无额度普通发表；不会向 QQ 或空间发送内容。

代码与来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。从 GitHub 的 **Code → Download ZIP** 可下载完整资料包。
