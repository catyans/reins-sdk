# Reins Python SDK

[English](README.md)

这是给现有 Agent 程序使用的轻量客户端，可接入托管版 Reins，也可连接同一台 Mac 上的 Reins 应用。在付费模型调用前预留费用，调用后记录实际费用和验收结果。**Agent、模型调用和提供商密钥都留在你的应用中。**本仓库不包含托管服务端或部署凭证。

## 接入 Reins Mac 应用

在运行 Agent 的同一台 Mac 上安装 SDK，不需要账号、配对码或额外启动服务。应用的 **Programs** 页面每十秒读取一次本地任务记录。

```python
from reins_sdk import Charge, LocalReinsClient

reins = LocalReinsClient()
task = reins.start_task(workflow="资料核查", budget="0.50",
                        wrapup_reserve="0.05", max_operations=20)

def call_model():
    response = your_existing_model_call()
    return Charge(result=response.text, actual_cost=response.cost_usd,
                  usage={"input_tokens": response.input_tokens,
                         "output_tokens": response.output_tokens})

answer = reins.run_paid_call(task_id=task, model="your-model", max_cost="0.10",
                             operation_key="核查第一份资料", execute=call_model)
reins.finish_task(task, accepted=your_acceptance_check(answer.result))
```

每次运行新建一个 task；SDK 在付费调用前原子化预留上限，预算不足时抛出 `AdmissionDenied`，不会调用模型。`wrapup_reserve` 留出收尾额度，收尾操作指定 `phase="wrapup"`；`operation_key` 防止同一任务的重复步骤，`max_operations` 限制循环。费用不明的调用继续占用预算，直至通过 `settle()` 核实；SDK 不会自动重复付费调用。只有接入 SDK 的调用才受控制。

Mac 页面分别显示已确认支出、未结算预留、拒绝的调用、合格交付数量及每份合格成果的成本。要比较节省效果，为同一工作流的两次运行设置相同 `case_id`，并分别标记 `variant="baseline"` 和 `"candidate"`。只有两次都完成、验收通过且费用全部结算，才显示节省金额；拦截的潜在花费不会算成已节省。账本只存任务元数据、模型名称、token、费用和验收状态，不存 prompt、结果正文或密钥。可运行 [本地示例](examples/local_mac_demo.py)。

## 安装

需要 Python 3.10+，无运行时第三方依赖：

```bash
python -m pip install git+https://github.com/catyans/reins-sdk.git
```

独立演示时，客户运行 `python -m reins_sdk.pair` 生成私有配对码；我们用一个 Hosted task 在 Reins Settings 页面完成首次配对。以后每次运行调用 `ReinsClient.start_run()`，服务端自动创建独立记录并返回内部 ID，客户不用重复配对或输入 Task ID。步骤见 [Skill 安装与配对说明](docs/SKILL_INSTALL.md)。其他托管工作区仍由我们私下提供 worker token 和 HTTPS API 地址。凭证只放在客户后端，不放进浏览器、移动端或代码仓库。网页登录配对码不能当作 worker token。

托管 API 地址可能以 `/api` 或 `/v1` 结尾，例如 `https://reins.example.com/api`。请使用交付给你的工作区地址。

## 在现有模型调用外加一层控制

```python
import os
from reins_sdk import Charge, ReinsClient

client = ReinsClient(
    os.environ["REINS_BASE_URL"],
    token=os.environ["REINS_WORKER_TOKEN"],
)

def call_your_provider(config):
    response = your_provider.generate(model=config["model"], prompt="...")
    return Charge(
        result=response.output,
        actual_cost=response.cost_usd,
        usage={"input_tokens": response.input_tokens, "output_tokens": response.output_tokens},
        validated=your_business_check(response.output),
        validation_name="business-result-v1",
    )

outcome = client.run_paid_call(
    workflow_id="reins-中已创建的任务-id",
    execute=call_your_provider,
    max_cost="0.10",  # 美元计价的保守上限，不能只填平均费用。
)
print(outcome.result)
```

`run_paid_call` 先读取任务选定的配置和是否继续的决策，再预留费用；只有获准后才会调用你原有的模型客户端，最后登记实际费用。它**不会自动重试**付费调用。若调用已经发生、但结算没有得到确认，会抛出带有请求 ID 的 `SettlementUnknown`；应核对这次调用，不能直接重新调用模型。

多步骤 Agent 可以直接使用 `decision()`、`reserve()`、`settle()`、`uncertain()`、`progress()` 和 `status()`。详细边界见 [API 说明](docs/API.md)。要让编程助手适配现有客户代码，可安装[接入 Skill](docs/SKILL_INSTALL.md)。只有接入 SDK 的调用会受到控制。

## 数据边界

worker API 接收任务 ID、模型/配置、费用估计及实际费用、可选 token 用量，以及你主动提交的结果。SDK 不会自动上传 prompt 或原始文档；但传给 `settle(result=...)` 的内容会保存在 Reins，请按实际协议删减敏感结果。模型提供商密钥不会发送给 Reins。

## 本地测试

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

测试只使用本地模拟 HTTP 服务，不调用付费模型。SDK 使用 Python 标准库，不关闭 TLS 证书校验，也不会通过环境配置的代理发送 worker token。

本仓库采用 Apache-2.0 许可；Reins 服务端另行部署，不在本仓库中。
