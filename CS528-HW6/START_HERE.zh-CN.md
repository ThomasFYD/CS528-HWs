# HW6 使用说明

真实云端实验已完成：运行编号为 `20261103-015057-b504`。
10 万条请求已从原有 Cloud SQL 数据库迁移到 3NF 结构，迁移前后数据一致。
两个模型已在新建 VM 上训练并测试，结果已上传并下载校验。
清理检查通过：数据库已停止，VM、启动磁盘、子网和网络均已删除。
GitHub 目录：https://github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW6

最终报告位于 `report/CS528_HW6_Report.pdf`，简要证据位于 `report/evidence/`。
实际云端结果目录：

```text
gs://cs528-hw2-yf-2026/cs528-hw6/runs/20261103-015057-b504/
```

## 恢复登录

在 Mac 终端运行：

```bash
gcloud auth login fangyd@bu.edu
```

浏览器中选择 BU 账号并完成授权，终端出现登录成功提示后即可继续。

## 查看并运行

```bash
cd /Users/thomasfang/CS528/CS528-HWs/CS528-HW6
python3 infra.py plan
python3 infra.py preflight
bash run.sh
```

完整运行会启动原有数据库，新建一台临时 VM，执行迁移和模型训练，上传
两个预测文件，然后停止数据库、删除临时 VM 及其磁盘和网络。原有 HW5
表保留，HW6 的规范化结果放在独立的 `hw6` 数据库。

程序最终会打印两个完整预测 CSV，输出较长。结果也保存在本地 `results/`
和原来的云端 bucket 中。下列结果来自实际 VM 运行。

## 云端实测结果

- 国家预测：100%（19,975 / 19,975）；训练集与测试集没有相同 IP。
- 收入预测：34.27%（6,854 / 20,000）；多数类别基线为 12.675%。
- 收入模型低于作业 35% 的目标，报告会如实解释，不替换测试集或挑选随机种子。
- 15 项本地测试通过，涵盖数据依赖、字段完整性、SQL 迁移的可重复性、测试集隔离和清理失败处理。

若运行被中断，使用程序输出的真实路径恢复清理：

```bash
python3 infra.py cleanup --state results/<run-id>/state.json
```

结束后检查该目录中的 `cleanup.json`，确认 `verified` 为 `true`。

如果模型输出已经上传，只需要恢复下载、清理检查与终端输出：

```bash
python3 infra.py resume --state results/<run-id>/state.json
```

本次运行曾在删除 VM 时遇到网络超时，删除本身已完成，之后恢复执行并重新检查。
原始记录保留在 `report/evidence/cleanup-before-retry.json`。
