"""Resolve a submission whose upstream response was lost after operator inspection."""
import argparse
from uuid import UUID

from .config import Settings
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="核对并恢复提交结果不明的任务")
    parser.add_argument("job_id", type=UUID)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--attach-upstream", metavar="VIDEO_ID", help="关联已核实的 SGLang 任务编号")
    action.add_argument("--confirm-failed", action="store_true", help="确认上游未接受请求，结束该任务")
    args = parser.parse_args()
    store = Store(Settings.from_env().database)
    try:
        store.resolve(str(args.job_id), args.attach_upstream)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"已更新任务 {args.job_id}")


if __name__ == "__main__":
    main()
