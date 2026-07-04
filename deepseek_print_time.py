import time
from datetime import datetime


def main() -> None:
    while True:
        now = datetime.now()
        print(now.strftime("%Y-%m-%d %H:%M:%S"))
        time.sleep(5)


if __name__ == "__main__":
    main()
