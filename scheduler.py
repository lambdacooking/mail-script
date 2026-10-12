"""check_mail.py 를 10초마다 실행하는 스케줄러.

사용법:
    python scheduler.py              # 기본 10초 간격
    python scheduler.py --interval 30
    python scheduler.py --timeout 900  # check_mail.py 1회 최대 실행 시간(초), 기본 600
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

SCRIPT = Path(__file__).resolve().parent / "check_mail.py"


def run_check(timeout):
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"--- {started} check_mail.py 실행")
    try:
        result = subprocess.run([sys.executable, str(SCRIPT)], timeout=timeout)
        if result.returncode != 0:
            print(f"[오류] check_mail.py 종료 코드 {result.returncode}")
    except subprocess.TimeoutExpired:
        print(f"[오류] check_mail.py 실행 시간 초과 ({timeout}초)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=10, help="실행 간격(초), 기본 10")
    parser.add_argument(
        "--timeout", type=int, default=600, help="check_mail.py 1회 최대 실행 시간(초), 기본 600 (Grok 분석 포함)"
    )
    args = parser.parse_args()

    print(f"스케줄러 시작: {args.interval}초마다 {SCRIPT.name} 실행 (Ctrl+C로 종료)")
    run_check(args.timeout)  # 시작 즉시 1회 실행
    schedule.every(args.interval).seconds.do(run_check, args.timeout)

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n스케줄러 종료")


if __name__ == "__main__":
    main()
