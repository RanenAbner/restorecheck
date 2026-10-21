"""Check: the restore produced a usable instance of the same engine as the snapshot."""
from checks.base import CheckResult

NAME = "instance_available"


def check_instance_available(target):
    instance, snapshot = target.instance, target.snapshot
    problems = []
    if instance.get("DBInstanceStatus") != "available":
        problems.append(f"status is {instance.get('DBInstanceStatus')!r}, expected 'available'")
    if instance.get("Engine") != snapshot.get("Engine"):
        problems.append(
            f"engine is {instance.get('Engine')!r} but snapshot is {snapshot.get('Engine')!r}"
        )
    if problems:
        return CheckResult(NAME, False, "; ".join(problems))

    endpoint = instance.get("Endpoint", {})
    return CheckResult(
        NAME,
        True,
        f"{instance['Engine']} {instance.get('EngineVersion', '')} available at "
        f"{endpoint.get('Address', '?')}:{endpoint.get('Port', '?')}",
    )
