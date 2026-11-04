"""上游 Key 加密存储（Fernet / AES-128-CBC + HMAC）。主密钥来自环境变量 ROUTER_MASTER_KEY。"""
import os
from cryptography.fernet import Fernet


class KeyVault:
    def __init__(self, master: str | None = None):
        master = master or os.getenv("ROUTER_MASTER_KEY")
        if not master:
            raise RuntimeError("必须设置 ROUTER_MASTER_KEY（生成：python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'）")
        self.f = Fernet(master.encode())

    def encrypt(self, s: str) -> str:
        return self.f.encrypt(s.encode()).decode()

    def decrypt(self, s: str) -> str:
        return self.f.decrypt(s.encode()).decode()
