from core.logging import get_log_writer

from modules.logs.schemas import ClientLogItem


def save_client_logs(items: list[ClientLogItem]) -> int:
    if not items:
        return 0
    writer = get_log_writer()
    payloads = [item.to_log_payload() for item in items]
    writer.write_client_logs(payloads)
    return len(payloads)
