"""KST 스케줄러 — 06:00/12:00/18:00/23:00 콘텐츠 사이클, 10:00 성과 수집.

주의사항(2026-09-20 반영):
- 단일 인스턴스 락: 스케줄러가 2개 뜨면 같은 사이클이 이중 게시되고
  source_log.xlsx 동시 쓰기로 행이 유실되므로 락 파일로 1개만 살린다.
- misfire_grace_time=2h: PC 절전으로 정각을 놓쳐도 깨어난 뒤 해당 사이클을
  실행한다(2026-09-20 12:00 사이클이 이 설정이 없어 통째로 누락됨).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

LOCK_NAME = "scheduler.lock"


def _lock_path() -> Path:
    base = Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base / LOCK_NAME


def _acquire_single_instance():
    """파일 락 획득. 실패(다른 인스턴스 실행 중) 시 False."""
    path = _lock_path()
    fh = open(path, "a")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def start(run_cycle, collect_metrics, run_shortform) -> None:
    handle = _acquire_single_instance()
    if handle is None:
        print(f"이미 스케줄러가 실행 중입니다 ({_lock_path()}). 새 인스턴스는 종료합니다.")
        return
    print(f"단일 인스턴스 락 획득 (pid={os.getpid()})")

    sch = BlockingScheduler(timezone="Asia/Seoul")
    common = {"misfire_grace_time": 7200, "coalesce": True, "max_instances": 1}
    sch.add_job(lambda: run_cycle("am"), CronTrigger(hour=6, minute=0), id="cycle-am", **common)
    sch.add_job(lambda: run_cycle("pm"), CronTrigger(hour=12, minute=0), id="cycle-pm", **common)
    sch.add_job(lambda: run_cycle("ev"), CronTrigger(hour=18, minute=0), id="cycle-ev", **common)
    sch.add_job(lambda: run_cycle("night"), CronTrigger(hour=23, minute=0), id="cycle-night", **common)
    sch.add_job(collect_metrics, CronTrigger(hour=10, minute=0), id="metrics", **common)
    # 숏폼 영상: 하루 3회 — 직전 콘텐츠 사이클의 명언으로 생성·발행
    for _h, _c in ((8, "am"), (13, "pm"), (19, "ev")):
        sch.add_job(lambda c=_c: run_shortform(c), CronTrigger(hour=_h, minute=0),
                    id=f"shortform-{_c}", **common)
    print("스케줄 등록: 06:00(am), 12:00(pm), 18:00(ev), 23:00(night),"
          " 08:00/13:00/19:00(숏폼), 10:00(metrics) KST"
          " — 절전에서 깨어나도 2시간 내에는 소급 실행됨")
    try:
        sch.start()
    finally:
        sys.stdout.flush()
        handle.close()
