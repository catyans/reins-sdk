# Worker API contract

The SDK is a thin client. Its request bodies match the hosted worker API; it does not decide whether a result is acceptable or calculate the provider's true bill.

| Method | Purpose | Important response |
| --- | --- | --- |
| `decision(workflow_id)` | Get pinned configuration and continue/escalate/stop | `action`, `configuration`, `budget_work_remaining` |
| `reserve(task_id, request_id, model, max_cost)` | Ask permission before a paid operation | `decision` (`continue`, `pause`, or `hold`) |
| `settle(request_id, actual_cost, ...)` | Record the actual charge after dispatch | `status` |
| `uncertain(request_id)` | Keep an unknown provider charge visible | `status` |
| `status(workflow_id)` | Read the saved task record | `workflows` |
| `progress(task_id, stage, completed, total)` | Report measured task progress | `status` |
| `pairing()` | Check the customer account connected to a demo pairing | `customer_id`, `deployment_id` |
| `start_run(run_key=None)` | Start a new run from the paired customer's approved deployment | `workflow_id` |

Use a unique, stable `request_id` for each actual provider call. If an HTTP response is lost, **do not create a new request ID and dispatch the provider call again**. Reins may already hold a reservation. Check the task record and reconcile the original request.

`run_paid_call()` covers one model operation with a pinned model in the plan. It requires your callback to return `Charge(result, actual_cost, usage)`. It does not support asynchronous callbacks; use the explicit methods in an async application. A `stop` or `hold` means the callback is not invoked. Reins can pause a task for a quality failure and request a new decision; it cannot undo a charge already incurred.

If you provide `Charge(validated=..., validation_name=...)`, Reins records the named business check. A failed named check can cause the hosted runtime to choose its qualified fallback or stop later calls. `success` describes the provider operation; it is not a substitute for the business check.

For the isolated paired demo, a Reins operator approves the deployment and performs the first pairing. The worker then calls `start_run()` for each business run; no task ID needs to be entered by a person. Each run still receives a separate internal ID so its budget, outcome and replay remain independent. If the start response is lost, pass the same `run_key` on retry to avoid a duplicate task. The worker token cannot change operator settings. The browser pairing token is for the dashboard only. A single shared pilot workspace is **not** a production multi-customer tenant setup.
