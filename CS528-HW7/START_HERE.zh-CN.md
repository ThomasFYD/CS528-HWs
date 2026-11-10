# HW7 提交与查看说明

提交文件：[CS528_HW7_Report.pdf](report/CS528_HW7_Report.pdf)。
报告已包含 [GitHub 源码链接](https://github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW7)。

本次实验使用 HW2 原始桶中的全部 12,000 个网页：

- 本地：722.983 秒（12.05 分钟），8 个工作线程。
- Dataflow：1033.472 秒（17.22 分钟），2 台工作节点。
- 三个 Top 5、所有完整计数及全部文件校验值均一致。
- 原始生成器独立核验通过，12 项测试通过。
- 云端工作节点和磁盘已释放；保留小型结果桶、运行证据和专用身份。

第一轮本地多进程运行遇到连接超时，已保留失败记录；报告采用成功的线程模式重跑时间。

查看结果：[打印输出](report/evidence/printed-results.txt)。
完整结果备份：[verified-output.zip](report/evidence/verified-output.zip)。
复现步骤：[README.md](README.md)。

如需重新运行，请使用新的运行标签。运行会读取原始 GCS 数据，云端运行会重新创建临时工作节点。
