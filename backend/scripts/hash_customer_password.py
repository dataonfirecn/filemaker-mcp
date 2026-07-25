from getpass import getpass

from app.services.customer_chat_auth import hash_customer_password


def main() -> None:
    password = getpass("客户登录密码：")
    confirmation = getpass("再次输入密码：")
    if password != confirmation:
        raise SystemExit("两次输入的密码不一致。")
    print(hash_customer_password(password))


if __name__ == "__main__":
    main()
