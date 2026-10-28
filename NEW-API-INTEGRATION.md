# Cloudi AI → new-api 渠道对接指南

> 本文档面向要在 new-api（one-api 系）里接入 Cloudi 2API 的操作者。
> 2API 服务由本仓库 `demo_server.py` 提供，OpenAI 兼容协议。

## 一、架构总览

```
new-api 渠道(type: OpenAI 自定义)
   │  base_url = http://<your-2api-host>:8902/v1
   │  api_key  = 任意非空(demo 未鉴权)
   ▼
demo_server.py (本仓库)
   │  AES-256-CBC 时间窗签名 + Firebase Remote Config 动态密钥
   ▼
nano-banana.leansoft-ai.com (Cloudflare Workers 上游)
```

## 二、启动 2API 服务

```bash
pip install pycryptodome
python demo_server.py 8902        # 生产建议放内网/带反代
```

健康检查：

```bash
curl http://127.0.0.1:8902/health
# {"service":"cloudi-2api","upstream":"https://nano-banana.leansoft-ai.com","status":"ok"}
```

> 密钥自动跟随：服务启动时从 Firebase Remote Config 拉取 `aes_key/aes_iv/base_url`，
> 厂商轮换密钥无需改代码。可用环境变量 `CLOUDI_BASE_URL` 覆盖上游。

## 三、new-api 渠道配置

在 new-api 管理后台 → 渠道 → 添加渠道：

| 配置项 | 值 |
|---|---|
| 类型 | **OpenAI** |
| 名称 | `cloudi-2api` |
| Base URL | `http://127.0.0.1:8902` （或你部署 2API 的主机地址；**不要带 `/v1`**，new-api 会自动拼接） |
| 密钥 | `sk-cloudi` （任意非空即可，2API 侧未做鉴权；建议在 2API 前加反代鉴权） |
| 模型 | 手动填入下表模型 ID |
| 模型重定向 | 不需要（2API 侧已做映射） |

### 可用模型 ID

| 模型 ID | 实际能力 | 计费建议 |
|---|---|---|
| `cloudi-enhance` | 图片增强（上传图 → 高清修复），**免费无墙** | 按 1x 图价 |
| `cloudi-nano-banana` | prompt 文生图（基于底图） | ⚠️ 见「已知限制」#1 |
| `cloudi-video` | 视频生成 | ❌ 上游已死，勿上架 |

### 请求示例（经 new-api）

```bash
# 图片增强
curl http://<new-api>/v1/images/edits \
  -H "Authorization: Bearer <new-api-token>" \
  -F model=cloudi-enhance -F image=@photo.jpg

# 文生图（chat 形式桥接）
curl http://<new-api>/v1/chat/completions \
  -H "Authorization: Bearer <new-api-token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"cloudi-nano-banana","messages":[{"role":"user","content":"a cute red apple"}]}'
```

## 四、直连 2API（不走 new-api）

2API 本身就是 OpenAI 兼容的，可直连测试：

```bash
curl http://127.0.0.1:8902/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"cloudi-nano-banana","messages":[{"role":"user","content":"a red apple"}]}'

# 图片增强（base64 jpeg）
curl -X POST http://127.0.0.1:8902/v1/image/enhance \
  -H "Content-Type: application/json" \
  -d '{"image_b64":"<base64>"}'

# 会话引导（返回 SaasID + 配额）
curl http://127.0.0.1:8902/v1/session
```

## 五、已知限制（重要）

1. **`cloudi-nano-banana` 文生图当前返回上游 `tokenData=null` 错误**。
   上游 worker 在 upload↔generate 之间有服务端会话绑定，需真机 Frida 抓包补齐
   （x86_64 模拟器被 ndk_translation W^X 限制，frida Java hook 必崩）。
   补齐前该模型不可上架计费。
2. **IP 信誉墙**：上游 Cloudflare 会拉黑直连 IP（`SSL UNEXPECTED_EOF`）。
   2API 服务器建议挂出口代理（住宅/机场线路可用；免费代理池过不了 CF）。
   代理环境变量方式：`HTTPS_PROXY=http://127.0.0.1:10808 python demo_server.py 8902`。
3. **视频已死**：上游返回 `DOMAIN_SUSPENDED`，`cloudi-video` 不要上架。
4. **配额**：免费设备 5 次/日出图 + 30 coins；`/v1/session/rewarded` 可 +50 coins；
   每次生成自动注册新设备，额度按设备轮换。
5. **并发**：设备注册 15 并发 100% 成功；建议 new-api 渠道并发 ≤8，过高触发 CF 断连。

## 六、生产化建议

| 项 | 建议 |
|---|---|
| 鉴权 | 2API 前加 nginx 反代 + API key 校验 |
| 出口 | 常驻住宅代理或机场出口，轮换周期 >1h |
| 监控 | `/health` 纳入拨测；关注 `aes_key_prefix` 变化（=厂商换密钥） |
| 模型 | 先只上架 `cloudi-enhance`（稳定），文生图等 tokenData 补齐 |
| 计费 | enhance 按张计；组价 = 上游免费，纯利润 |

## 七、故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `health` 里 `status: ok` 但生成 502 | 上游 CF 拉黑本机 IP | 挂出口代理 |
| `Invalid decrypted format` | X-Client-Auth 时间窗过期（>60s） | 检查服务器时钟 NTP |
| `Quota limit` | IP 信誉差被上游惩罚 | 换出口 |
| 大量 `SSL EOF` | 并发过高 | 降低渠道并发到 ≤8 |
| `DOMAIN_SUSPENDED` | 视频上游死了 | 下架 video 模型 |
