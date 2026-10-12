"""check_mail.py 를 10초마다 실행하는 스케줄러.

사용법:
    python scheduler.py              # 기본 10초 간격
    python scheduler.py --interval 30
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

SCRIPT = Path(__file__).resolve().parent / "check_mail.py"


def run_check():
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"--- {started} check_mail.py 실행")
    try:
        result = subprocess.run([sys.executable, str(SCRIPT)], timeout=60)
        if result.returncode != 0:
            print(f"[오류] check_mail.py 종료 코드 {result.returncode}")
    except subprocess.TimeoutExpired:
        print("[오류] check_mail.py 실행 시간 초과 (60초)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=10, help="실행 간격(초), 기본 10")
    args = parser.parse_args()

    print(f"스케줄러 시작: {args.interval}초마다 {SCRIPT.name} 실행 (Ctrl+C로 종료)")
    run_check()  # 시작 즉시 1회 실행
    schedule.every(args.interval).seconds.do(run_check)

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n스케줄러 종료")


if __name__ == "__main__":
    main()
