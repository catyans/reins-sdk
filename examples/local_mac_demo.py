"""Run a zero-provider-cost demonstration of the Reins Mac SDK bridge."""

from reins_sdk import Charge, LocalReinsClient


def main():
    client = LocalReinsClient()
    task = client.start_task(workflow="sample-document-review", budget="0.02",
                             wrapup_reserve="0.002", max_operations=4)
    # Replace this callback with the existing provider call in your own program.
    charge = client.run_paid_call(
        task_id=task, model="example-reported-usage", max_cost="0.01",
        operation_key="review-1",
        execute=lambda: Charge("Reviewed one sample document", "0.000350",
                               {"input_tokens": 300, "output_tokens": 70}),
    )
    client.finish_task(task, accepted=True)
    print(f"Task {task}: {charge.result}")
    print("This example records a supplied charge; it makes no model API call.")
    print(client.summary())


if __name__ == "__main__":
    main()
