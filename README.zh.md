# 本地版 Whisper Flow(语音听写工具)

**[English → README.md](README.md)**

一个完全本地、离线运行的 macOS 语音输入工具(Apple Silicon)。
按住快捷键说话,松开后文字自动粘贴到当前光标处 —— 所有处理都在你自己的
电脑上完成,**任何数据都不会离开本机**。

## 工作流程

```
fn 键 → 麦克风采集 (16kHz) → Silero VAD → SenseVoice 语音识别 → Ollama 润色 → 粘贴到当前应用
```

语音识别用的是阿里的 **SenseVoice-Small**(通过 sherpa-onnx 运行)——
专门针对**中英混说**训练,内置标点和数字归一化。实测:5.6 秒的中文音频
**0.07 秒**出结果。Whisper(mlx / faster-whisper)保留为备选后端,可在
`config.py` 中切换。

### 模型文件

SenseVoice 模型放在 `models/` 目录(不入库)。重新下载:

```bash
mkdir -p models && cd models
curl -sLO https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
tar xjf sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2 && rm *.tar.bz2
```

## 安装

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

然后下载 SenseVoice 模型(见上面"模型文件"),如需 AI 润色再安装
Ollama(见下面"LLM 润色")。一次性下载完成后,全程 100% 离线运行。

## macOS 权限(必须)

在 **系统设置 → 隐私与安全性** 中,给你的**终端应用**(Terminal / iTerm)
授予以下权限:

| 权限         | 用途                          |
|--------------|-------------------------------|
| 麦克风       | 录制你的语音                  |
| 辅助功能     | 模拟 Cmd+V 粘贴文字           |
| 输入监控     | 捕获全局快捷键(fn)          |

第一次运行时 macOS 会弹出麦克风授权;如果按了 fn 没反应或者文字粘不出来,
手动把终端加进"辅助功能"和"输入监控"再重启终端。

## 运行

```bash
./.venv/bin/python main.py
```

三种交互方式:

- **按住 fn** — 对讲机模式:按住说话,松开即转写粘贴
- **轻点 fn** — 免按模式:自由地说,再点一下 fn 或停顿约 2 秒
  (Silero VAD 自动判停)即结束
- **按住 shift+fn** — 翻译模式:说中文(或中英混杂),粘贴出来的是
  地道英文(目标语言可通过 `TRANSLATE_TARGET` 修改)。录音过程中任何
  时候按 shift 也能切换,先按哪个键都无所谓
- **双击 fn** — 快速开关 AI 润色(不需要打开菜单)

听写时屏幕底部会浮现一个胶囊指示条:**● Listening… / ⏳ Processing…**
(悬浮于所有窗口之上、鼠标可穿透、所有桌面空间可见)。
菜单栏图标同步显示状态(🎙 / 🔴 / ⏳),菜单里有:

- **AI Cleanup (qwen2.5)** — 实时开关 LLM 润色
- **History** — 最近 5 条转写记录(跨会话永久保存),点击即复制

录音开始/结束有轻微提示音。从菜单栏 Quit 或终端 Ctrl+C 退出。

> **fn 键设置:** 把 **系统设置 → 键盘 → "按下 🌐 键时" 设为"无操作"**,
> 否则按住 fn 会同时弹出表情符号面板或触发 macOS 自带听写。

只想测试快捷键(不录音):

```bash
./.venv/bin/python hotkey.py   # 按 fn 时打印 DOWN/UP
```

## 配置

所有开关都在 [`config.py`](config.py):

- `STT_BACKEND` — `sensevoice`(默认,中英混说最佳)· `mlx`(Whisper 走
  Apple GPU)· `faster-whisper`(Whisper 走 CPU)
- `HOTKEY` — `"fn"`(默认,🌐 键)或任意 pynput 组合键,如
  `"<ctrl>+<alt>+<space>"`
- `TAP_THRESHOLD` / `VAD_SILENCE` — 轻点/按住的判定阈值、免按模式自动
  结束所需的静音秒数
- `CLEANUP_ENABLED` / `CLEANUP_MODEL` — LLM 润色开关和 Ollama 模型
- `CLEANUP_MIN_TOKENS` — 低于此长度的短句跳过 LLM 润色
  (按"汉字数 + 英文单词数"计,默认 8,设 `0` 则全部润色)
- `DICTIONARY_ENABLED` / `DICTIONARY_FILE` — 个人词典(见下文)
- `TRANSLATE_ENABLED` / `TRANSLATE_TARGET` — shift+fn 翻译模式及目标语言
- `INJECT_METHOD` — `paste`(默认,最稳)或 `type`(直接模拟键入,
  适合 Terminal / VS Code);`INJECT_OVERRIDES` 可按应用自动切换
  (Terminal / iTerm / VS Code 默认已配成 `type`)
- `TWO_STAGE_PASTE` — 两段式粘贴:原始转写**立刻**上屏,约 1 秒后 LLM
  润色版原地替换。期间你打字、点击或切换应用都会自动放弃替换,
  绝不会碰到刚粘贴内容以外的任何文字
- `SOUNDS_ENABLED` / `MENU_BAR` / `OVERLAY_ENABLED` — 界面相关开关

## 文件说明

| 文件            | 职责                                         |
|-----------------|----------------------------------------------|
| `main.py`       | 主流程编排 + 菜单栏                          |
| `hotkey.py`     | fn 键(Quartz 事件监听)/ 组合键监听         |
| `overlay.py`    | 悬浮录音指示条(NSPanel)                    |
| `vad.py`        | 免按模式的 Silero VAD 自动判停               |
| `cleanup.py`    | Ollama LLM 文本润色                          |
| `sounds.py`     | 开始/结束提示音                              |
| `audio.py`      | 麦克风采集                                   |
| `transcribe.py` | 语音识别封装(SenseVoice / mlx / faster-whisper)|
| `dictionary.py` | 个人词典(识别后查找替换)                   |
| `inject.py`     | 剪贴板粘贴 / 模拟键入                        |
| `config.py`     | 全部配置                                     |

## 翻译模式

按住 **shift+fn** 说中文(或平时的中英混杂),粘贴出来的直接是地道英文 ——
边用中文思考、边写英文邮件/Slack 特别好用。录音时悬浮条显示
`● → English…`、菜单栏图标变成 🌐,一眼就能分清当前模式。翻译用的是和
润色同一个本地 Ollama 模型(翻译时自动忽略口头填充词);任何失败都会
退回粘贴原文,不会丢字。`TRANSLATE_TARGET` 可改成模型认识的任何语言
(比如 `"日本語"`)。

## 个人词典

语音模型经常认错专有名词(产品名、人名、术语)。在
`~/.config/whisperflow/dictionary.json` 里一次性纠正(首次运行会自动
创建示例文件),格式为 `"错的": "对的"`:

```json
{
  "cloud code": "Claude Code",
  "克劳德": "Claude"
}
```

纯英文的键按完整单词匹配、不区分大小写(中英交界如 `用cloud code和`
也能匹配);含中文的键按原样精确匹配。以 `_` 开头的键是注释。
修改后下一次听写即生效,无需重启。

## LLM 润色

转写结果会经本地 LLM(Ollama 上的 `qwen2.5:7b`)润色:去掉口头填充词
(嗯/呃/那个/um/uh)、修正标点 —— 中英混杂**原样保留,绝不翻译**
(通过 few-shot 示例约束)。每句约增加 1 秒,因此短句(低于
`CLEANUP_MIN_TOKENS`,默认 8)会跳过润色直接粘贴;设
`CLEANUP_ENABLED = False` 可完全关闭。`cleanup.py` 检测到 Ollama 没启动时会自动拉起。

```bash
brew install ollama && ollama pull qwen2.5:7b   # 一次性安装
```

## 开机自启(可选)

项目里附带了 LaunchAgent 配置文件,但**默认没有安装**。启用:

```bash
cp com.whisperflow.dictation.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.whisperflow.dictation.plist
```

注意:通过 launchd 运行时,macOS 会针对 python 二进制重新弹出
麦克风/辅助功能/输入监控的授权。日志在 `/tmp/whisperflow.log`。
停用:`launchctl unload ~/Library/LaunchAgents/com.whisperflow.dictation.plist`。
