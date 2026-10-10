# Reins Python SDK

[English](README.md)

这是给客户后端使用的轻量客户端，用于接入托管版 Reins：在付费模型调用前获取运行决策和费用预留，调用后记录实际费用，并查询任务状态。**Agent、模型调用和提供商密钥都留在你的应用中。**本仓库不包含 Reins 服务端、策略引擎、数据库、网页或部署凭证。

## 安装

需要 Python 3.10+，无运行时第三方依赖：

```bash
python -m pip install git+https://github.com/catyans/reins-sdk.git
```

我们会通过私下渠道提供该工作区的 **worker token** 和 HTTPS API 地址。把 token 放在后端的密钥管理环境中，不要放入浏览器、移动端或代码仓库。网页的一次性配对码不能当作 worker token。任务及其已审核配置需要先由 Reins 端创建。

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

多步骤 Agent 可以直接使用 `decision()`、`reserve()`、`settle()`、`uncertain()`、`progress()` 和 `status()`。详细边界见 [API 说明](docs/API.md)。只有接入 SDK 的调用会受到控制。

## 数据边界

worker API 接收任务 ID、模型/配置、费用估计及实际费用、可选 token 用量，以及你主动提交的结果。SDK 不会自动上传 prompt 或原始文档；但传给 `settle(result=...)` 的内容会保存在 Reins，请按实际协议删减敏感结果。模型提供商密钥不会发送给 Reins。

## 本地测试

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

测试只使用本地模拟 HTTP 服务，不调用付费模型。SDK 使用 Python 标准库，不关闭 TLS 证书校验，也不会通过环境配置的代理发送 worker token。

本仓库采用 Apache-2.0 许可；Reins 服务端另行部署，不在本仓库中。
