# CS528 HW3: 第一版云端文件服务

这是分阶段教学中的阶段 2，先实现文件读取、HTTP 状态码和错误日志。
国家过滤、Pub/Sub 发布以及第二个本地服务将在后续阶段加入。
当前版本还不是最终可提交的完整 HW3。

## 已确认的资源

- Project: `dazzling-seat-508219-j3`
- Bucket: `cs528-hw2-yf-2026`
- 文件前缀: `data/`
- 运行身份: `cs528-hw3-sa@dazzling-seat-508219-j3.iam.gserviceaccount.com`
- 部署区域: `us-central1`
- 函数名称: `cs528-hw3-files`
- Python 函数入口: `get_file`

## 接口

| 请求 | 行为 |
| --- | --- |
| `GET /cs528-hw2-yf-2026/data/0.html` | 去掉 bucket 前缀，读取 `data/0.html`，返回原始字节和 200 |
| `GET /data/0.html` | 直接读取 `data/0.html`，返回原始字节和 200 |
| `POST /`，JSON 为 `{"filename":"data/0.html"}` | 按 payload 中的 filename 读取，返回 200 |
| GET/POST 请求不存在的文件 | 返回 404，并输出普通文本和结构化 JSON 日志 |
| PUT、DELETE、HEAD、CONNECT、OPTIONS、TRACE、PATCH 等其他方法 | 函数处理器返回 501，并输出两种日志 |
| 无效 POST JSON | 返回 400，并输出两种日志 |
| 存储权限或服务故障 | 返回 500，避免误报成文件不存在 |

HEAD 在 HTTP 层没有响应正文，但状态码仍然应为 501。
本版本只通过函数提供 `data/` 下的数据集，`hw3-logs/` 不属于文件服务的接口范围。
HW2 bucket 自身仍有 allUsers 读取权限；上述路径限制仅作用于函数入口。

## 代码中的四个部分

1. `get_bucket()` 在第一次读取时创建 Storage 客户端，并复用它。云端从附加的运行 service account 获取凭证。
2. `object_name_from_filename()` 把客户端的 bucket 前缀去掉。`cs528-hw2-yf-2026/data/8471.html` 对应的对象名是 `data/8471.html`。
3. `error_response()` 为每个错误分别打印一行文本和一行 JSON，供 Cloud Logging 收集。
4. `get_file()` 先检查 HTTP method，再取文件名，最后读取对象并返回内容。

`requirements.txt` 固定了本次本地测试使用的两个直接依赖版本。

## 部署

在本目录执行：

```bash
gcloud functions deploy cs528-hw3-files \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --project=dazzling-seat-508219-j3 \
  --source=. \
  --entry-point=get_file \
  --trigger-http \
  --allow-unauthenticated \
  --service-account=cs528-hw3-sa@dazzling-seat-508219-j3.iam.gserviceaccount.com \
  --set-env-vars=BUCKET_NAME=cs528-hw2-yf-2026 \
  --memory=256Mi \
  --timeout=60s \
  --min-instances=0 \
  --max-instances=2
```

`--allow-unauthenticated` 让浏览器、curl 和老师的客户端可以调用 HTTP 入口。
`--service-account` 指定函数读取 Storage 时使用的运行身份。
构建程序所用的 build service account 是另一种身份；如果首次部署出现 build 权限错误，应按具体错误诊断。

部署完成后获取实际服务 URL：

```bash
gcloud functions describe cs528-hw3-files \
  --gen2 \
  --region=us-central1 \
  --project=dazzling-seat-508219-j3 \
  --format="value(serviceConfig.uri)"
```

## 客户端探测记录

用户在 Mac 上用老师提供的 arm64 客户端执行单次本地测试，观察到：

```text
Request path: cs528-hw2-yf-2026/data/8471.html
X-country: 'Cabo Verde'
```

这个 request-target 没有前导 `/`。正式调用云端时，应让路径以 `/` 开头。
根据这次拼接结果，下一步将尝试把客户端的 `-b` 参数设为 `/cs528-hw2-yf-2026`，并用实际请求验证。
这里改变的是客户端构造 URL 的参数，真实 bucket 名称仍为 `cs528-hw2-yf-2026`。

## 本地验证范围

已使用 Python 3.12、Functions Framework 3.10.2 和模拟的 Storage 客户端通过 10 项测试。
测试覆盖原样返回内容、两种 GET 路径、POST payload、404 和两种错误日志、所有题目列出的其他 HTTP 方法、HEAD 无正文、无效 payload、存储权限故障及日志目录隔离。

这些测试没有访问真实云端，也不能证明 Google Cloud 入口对 CONNECT/TRACE 等方法的处理行为。
尚待用户部署后验证真实 Storage 读取、HTTP 入口和 Cloud Logging。

如需复现测试，在安装 requirements.txt 的独立环境中运行：

```bash
python -m unittest discover -s tests -v
```

## 参考

- [Google: Python HTTP functions](https://docs.cloud.google.com/run/docs/write-functions)
- [Google: gcloud functions deploy](https://docs.cloud.google.com/sdk/gcloud/reference/functions/deploy)
- [Google: Structured logging](https://docs.cloud.google.com/logging/docs/structured-logging)
- [RFC 9112: HTTP request-target origin-form](https://www.rfc-editor.org/rfc/rfc9112.html#section-3.2.1)
