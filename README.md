---
title: Streamlit Application Service
emoji: 🔊
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Streamlit Application Service

独立的 Streamlit 服务服务端。它与旧的 .NET 4.5、.NET 8 和 PHP 项目完全独立。

## 同一站点的两种用途

浏览器访问根目录时看到正常 Streamlit 应用（在线文字转语音）；独立客户端访问同一个域名下的 `/api/service/v1/*` 时进入服务 API。

API 与 Streamlit UI 使用同一个 Python 进程、同一个 Tornado Web Application、同一个监听端口。`run_streamlit.py` 会在 Streamlit 开始监听前挂载 API 路由，因此不要求先有人打开浏览器。

## 服务协议

- `GET /api/service/v1/health`
- `POST /api/service/v1/open`
- `POST /api/service/v1/session/{id}/send`
- `GET /api/service/v1/session/{id}/receive?wait=10000&max=65536`
- `POST /api/service/v1/session/{id}/close`
- 请求头：`X-App-Key`

传输采用有限长度 POST + 有界长轮询，不依赖持续 chunked upload，更适合 Streamlit 前面的反向服务。

目标 TCP Session 保存在 Streamlit Python 进程内存中。服务进程重启、休眠或被平台重新调度时，当前 TCP Session 会自然失效，客户端的新连接可以重新建立 Session。

## 配置

推荐在空间的 Secrets / 环境变量中设置：

```text
APP_SERVICE_KEY=<足够长的随机值>
```

其他可选项：

```text
APP_CONNECT_TIMEOUT_SECONDS=15
APP_SESSION_IDLE_TIMEOUT_SECONDS=180
APP_MAX_CONCURRENT_SESSIONS=64
APP_ALLOW_PRIVATE_ADDRESSES=false
APP_MAX_SEND_BYTES=262144
APP_MAX_RECEIVE_BYTES=65536
APP_MAX_LONG_POLL_SECONDS=15
```

也可以参考 `.streamlit/secrets.toml.example`。不要把真实 API Key 提交到公开仓库。

## Hugging Face / Docker Space

本目录可以直接作为 Docker Space 内容。Dockerfile 会运行：

```text
python run_streamlit.py
```

并监听平台提供的 `PORT`，默认 7860。

浏览器仍然得到标准 Streamlit UI；Docker 只是确保 API 路由能在 Streamlit 开始监听前挂载，并不把网站替换成其他 Web 框架。

## 本地运行

```powershell
$env:APP_SERVICE_KEY="your-long-random-key"
python run_streamlit.py
```

默认端口 8501。也可以设置 `PORT`。

## 安全默认值

默认 `APP_ALLOW_PRIVATE_ADDRESSES=false`，拒绝 loopback、RFC1918、link-local、multicast、reserved 等目标地址，并且解析域名后直接连接已验证的 IP 地址，避免简单的 DNS 重绑定绕过。

公开部署时建议：

- 使用强随机 `APP_SERVICE_KEY`；
- 保持私网访问关闭；
- 不要在公开 UI 中显示 API Key；
- 使用单实例或确保同一 Session 的 HTTP 请求有粘性路由；
- 注意托管平台可能限制任意出站 TCP 端口，代码允许 1-65535 不代表每个空间平台都允许这些端口。

## 已完成的本地验证

- Streamlit UI `AppTest`：0 exception；
- API 在浏览器访问 UI 之前即可使用；
- X-App-Key 鉴权；
- open/send/receive/close；
- Session 关闭后 activeSessions 回到 0；
- 独立客户端普通 HTTP 转发；
- 独立客户端 CONNECT 双向字节流；
- 通过 CONNECT 实际完成 HTTPS TLS 请求。
