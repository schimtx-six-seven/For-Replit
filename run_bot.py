"""Supervisor simples para manter o processo do bot vivo no workflow."""

import os
import signal
import subprocess
import sys
import time


child = None
stopping = False


def stop_supervisor(_signum, _frame):
    global stopping
    stopping = True
    if child is not None and child.poll() is None:
        child.terminate()


def main():
    global child
    delay = 5
    signal.signal(signal.SIGTERM, stop_supervisor)
    signal.signal(signal.SIGINT, stop_supervisor)

    while not stopping:
        preflight = subprocess.run(
            [sys.executable, "-m", "py_compile", "main.py"],
            check=False,
        )
        if preflight.returncode != 0:
            print(
                "❌ Pré-verificação falhou; bot não iniciado. "
                "Nova tentativa em 60s.",
                flush=True,
            )
            for _ in range(60):
                if stopping:
                    break
                time.sleep(1)
            continue

        print("🛡️ Supervisor Valkyrie iniciando o bot...", flush=True)
        child = subprocess.Popen(
            [sys.executable, "main.py"],
            env=os.environ.copy(),
        )
        return_code = child.wait()
        child = None

        if stopping:
            return 0

        if return_code == 78:
            print(
                "⛔ Erro de configuração que exige ação manual "
                "(DISCORD_TOKEN); supervisor encerrado sem reiniciar.",
                flush=True,
            )
            return 78

        if return_code == 0:
            delay = 5
            print("ℹ️ O bot encerrou normalmente; reiniciando em 5s.", flush=True)
            time.sleep(5)
            continue

        print(
            f"⚠️ O bot encerrou com código {return_code}; "
            f"reiniciando em {delay}s.",
            flush=True,
        )
        time.sleep(delay)
        delay = min(delay * 2, 60)


if __name__ == "__main__":
    raise SystemExit(main())