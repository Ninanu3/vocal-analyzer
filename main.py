"""
main.py
=======
발성 분석 봇 진입점.

1. config.ini 없음 → Setup Wizard 실행 → config.ini 생성
2. config.ini 있음 → 설정에 맞는 모드로 바로 실행
"""

import configparser
import logging
import os
import sys

CONFIG_FILE = "config.ini"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg


def _run_wizard():
    """최초 실행 시 Setup Wizard 호출."""
    from wizard.wizard_main import run_wizard
    run_wizard()


def _run_mode(config: configparser.ConfigParser):
    execution = config.get("mode", "execution", fallback="local").strip()
    log.info(f"실행 모드: {execution}")

    if execution == "cloud":
        from modes.cloud_mode import run_cloud_mode
        run_cloud_mode(config)

    elif execution == "polling":
        from modes.polling_mode import run_polling_mode
        run_polling_mode(config)

    elif execution == "local":
        from modes.local_mode import run_local_mode
        run_local_mode(config)

    else:
        log.error(f"알 수 없는 실행 모드: {execution}")
        sys.exit(1)


def main():
    # ── Setup Wizard ─────────────────────────────
    if not os.path.exists(CONFIG_FILE):
        log.info("config.ini 없음 → Setup Wizard 시작")
        _run_wizard()

        if not os.path.exists(CONFIG_FILE):
            log.info("설정이 취소되었습니다.")
            sys.exit(0)

    # ── 모드 실행 ─────────────────────────────────
    config = _load_config()
    _run_mode(config)


if __name__ == "__main__":
    main()
