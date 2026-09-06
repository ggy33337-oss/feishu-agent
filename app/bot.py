# -*- coding: utf-8 -*-
import logging

from app.services.feishu_ws import FeishuWsBot
from app.services.logging_setup import configure_process_logging
from app.skills.search.skill import SearchSkill


logger = logging.getLogger(__name__)


def main() -> None:
    configure_process_logging("bot")
    logger.info("Loaded %s skill: three-layer query planning enabled", SearchSkill.name)
    FeishuWsBot().start()


if __name__ == "__main__":
    main()
