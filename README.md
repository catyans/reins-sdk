# Reins Python SDK

[简体中文](README.zh-CN.md)

A small, backend-only client for the hosted Reins worker API. It lets your existing Agent ask whether a task may continue, reserve a maximum cost before a paid model call, report the actual charge afterward, and inspect the task record. **Your model provider calls and API keys remain in your application.** This repository contains no Reins server, policy engine, database, dashboard, or deployment credentials.

## Install

Python 3.10+; the SDK has no runtime dependencies.

```bash
python -m pip install git+https://github.com/catyans/reins-sdk.git
```

Your Reins contact supplies a **worker token** and HTTPS API base URL through a private channel. Put the token in your backend's secret store, not in JavaScript, a mobile app, or a source file. The browser pairing token is a different credential and cannot be used here.

Your hosted API base may end in `/api` or `/v1` (for example, `https://reins.example.com/api`). Use the exact URL supplied for your workspace. A task and its approved configuration must be prepared on the Reins side before the worker can run it.

## First paid call

```python
import os
from reins_sdk import Charge, ReinsClient

client = ReinsClient(
    os.environ["REINS_BASE_URL"],
    token=os.environ["REINS_WORKER_TOKEN"],
)

def call_your_provider(config):
    # Use your existing provider client and its actual usage/cost reporting.
    response = your_provider.generate(model=config["model"], prompt="...")
    return Charge(
        result=response.output,
        actual_cost=response.cost_usd,
        usage={"input_tokens": response.input_tokens, "output_tokens": response.output_tokens},
        validated=your_business_check(response.output),
        validation_name="business-result-v1",
    )

outcome = client.run_paid_call(
    workflow_id="task-created-in-reins",
    execute=call_your_provider,
    max_cost="0.10",  # Conservative upper bound in USD, not average cost.
)
print(outcome.result)
```

`run_paid_call` requests the task's pinned configuration, reserves the upper bound, and calls your provider only if Reins admits the operation. It then records the actual charge. It never retries a paid call. If the provider response or charge is uncertain, the reservation stays visible for reconciliation. If settlement cannot be acknowledged, it raises `SettlementUnknown` with the request ID. Do not repeat the provider call to resolve that error.

For a multi-step Agent, use `decision()`, `reserve()`, `settle()`, `uncertain()`, `progress()`, and `status()` directly. [Explicit-call example](examples/explicit_calls.py) shows the boundary. The [API guide](docs/API.md) describes request IDs, budget decisions and error handling. The SDK only controls calls you connect to it.

## What is sent

The worker API receives the task ID, selected model/configuration, estimated and actual USD cost, optional token counts, and the result you choose to record. The SDK does not upload a prompt or document automatically. The `result` argument to `settle()` **does** go to Reins and is saved there; omit or redact sensitive output if your agreement requires it. Your provider keys never go to Reins.

## Test locally

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Tests use a local fake HTTP service and do not call a model provider or spend money. This client is synchronous and uses Python's standard library. It never disables TLS certificate verification and never sends its token through an environment-configured proxy.

Apache-2.0 licensed. The hosted Reins service is separate and is **not** part of this repository.
