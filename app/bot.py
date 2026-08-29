import logging

from app.services.feishu_ws import FeishuWsBot


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    FeishuWsBot().start()


if __name__ == "__main__":
    main()
