"""CLI commands for the Ralph Loop Orchestrator."""

from .add import format_add_human, handle_add
from .claim import format_claim_human, handle_claim
from .complete import format_complete_human, handle_complete
from .decompose import format_decompose_human, handle_decompose
from .fail import format_fail_human, handle_fail
from .heartbeat import format_heartbeat_human, handle_heartbeat
from .info import format_info_human, handle_info
from .init import format_init_human, handle_init
from .list import format_list_human, handle_list
from .log import format_log_human, handle_log
from .reclaim import format_reclaim_human, handle_reclaim
from .status import format_status_human, handle_status

COMMANDS = {
    "init": (handle_init, format_init_human),
    "add": (handle_add, format_add_human),
    "claim": (handle_claim, format_claim_human),
    "heartbeat": (handle_heartbeat, format_heartbeat_human),
    "complete": (handle_complete, format_complete_human),
    "fail": (handle_fail, format_fail_human),
    "decompose": (handle_decompose, format_decompose_human),
    "status": (handle_status, format_status_human),
    "list": (handle_list, format_list_human),
    "reclaim": (handle_reclaim, format_reclaim_human),
    "log": (handle_log, format_log_human),
    "info": (handle_info, format_info_human),
}
