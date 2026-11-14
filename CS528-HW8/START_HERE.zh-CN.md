# HW8 使用说明

本作业在 HW4 的基础上，为位于同一 region、不同 zone 的两个 Web 服务增加 Network Load Balancer，并实测故障切换和恢复。

## 已完成的结果

- 最终报告：[CS528_HW8_Report.pdf](report/CS528_HW8_Report.pdf)，沿用 HW6、HW7 的黑白版式，共六页。
- 三轮实测故障切换：25.31、23.41、27.22 秒；恢复：20.72、36.47、26.60 秒，均低于一分钟。
- 正常双后端稳定阶段：A 占 51.02%，C 占 48.98%。
- 40 项本地测试、32 项云端 HTTP 验证通过，464 次正式实验请求已归档。
- 本次创建的云资源已删除并核验。报告记录的 IP 仅作为历史证据。

## 查看代码

- `web_server.py`：保留 HW4 服务行为，新增 `X-Server-Zone` 响应头和 `/healthz` 健康检查。
- `client.py`：每秒发起一个请求，打印 zone、状态码和耗时，同时保留原始 JSONL 记录。
- `manage.py`、`startup.py`：建立、查看、清理云资源，以及自动安装和启动应用。
- `experiment.py`：真正终止一台 VM 上的 Web 进程，再恢复服务，记录三个实验轮次。
- `analyze.py`、`check_submission.py`、`collect_evidence.py`：计算结果、核验证据、整理提交材料。
- `README.md`：英文配置说明、实验方法与技术参考。

## 本地检查

在此文件夹中运行：

```bash
python3 -m unittest discover -s tests -v
python3 manage.py create --dry-run
```

## 重新进行云端实验

实际部署会创建计费云资源。原有 HW2 文件和 HW4 服务身份是前置条件。先确认 Google Cloud 登录有效，且 SSH 密钥已经加载，再运行：

```bash
python3 manage.py create
python3 manage.py status
```

等两个后端均为 `HEALTHY` 后：

```bash
python3 verify_live.py
python3 experiment.py --trials 3
```

实验会打印结果文件夹。把下方的 `RUN_FOLDER` 替换成该路径：

```bash
python3 check_submission.py RUN_FOLDER
python3 collect_evidence.py RUN_FOLDER
python3 manage.py delete
python3 collect_evidence.py RUN_FOLDER --finalize-cleanup
```

## 结果的含义

健康检查 API 状态变化与客户端真正观察到的流量变化是不同测量。
一次成功命中幸存 VM 不能证明故障后端已经被排除。分析会检查最后一次失败请求之后持续成功的序列。
恢复时间从远端开始重启服务，计到客户端首次完整收到恢复 VM 的 HTTP 200 响应。
每秒采样、随机连接分配和控制面查询延迟会影响观测精度，报告会明确这些限制。

请求占比以完整成功的 HTTP 200 文件响应为分母，并单独列出失败请求。
正常双后端阶段与人为关闭一个后端的阶段分开统计。
