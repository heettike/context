"""Signing in to telegram from the app, with no terminal: the same QR sign-in `python3 -m ctx telegram-login` does, as
a stream of events. Nothing is typed here. The owner scans a code with the telegram app on their phone.

    login(emit, stop)   emits {"qr": "<address to draw as a QR code>", "n": k, "of": 8} each time the code is renewed
                        (every 25 seconds, as telegram wants), then returns
                        {"state": "ok" | "needs_you" | "cannot", "detail": one plain sentence}

A two-step password is never asked for over this pipe: that case returns needs_you and names the one command to run in
a terminal, where the password goes straight to telegram's library and nowhere else.
"""
import asyncio, os
from . import paths

TRIES, EACH = 8, 25


def _client():
    from . import llm  # noqa: F401  (loads .env)
    from .collect import telegram_packages
    why = telegram_packages()       # this runs inside the app's engine: the same check as the collector's, never a bare sys.path
    try:
        from telethon import TelegramClient, errors
    except ImportError:
        return None, None, why or "telegram needs its packages (telethon and qrcode), kept inside this repo. in the repo folder: python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-telegram.txt"
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID", "").strip(), os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id.isdigit() or not api_hash:
        return None, None, "put TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first (my.telegram.org > api development tools)"
    return TelegramClient(os.path.join(paths.HOME, "telegram"), int(api_id), api_hash), errors.SessionPasswordNeededError, ""


async def _login(tg, needs_password, emit, stop, tries, each):
    await tg.connect()
    try:
        if await tg.is_user_authorized():
            return {"state": "ok", "detail": "already signed in to telegram"}
        qr = await tg.qr_login()
        for n in range(1, tries + 1):
            if stop is not None and stop.is_set():
                return {"state": "cannot", "detail": "stopped"}
            emit({"qr": qr.url, "n": n, "of": tries})
            try:
                await qr.wait(each)
                break
            except asyncio.TimeoutError:
                await qr.recreate()
            except needs_password:
                return {"state": "needs_you", "detail": "telegram wants your two-step password. it is typed in a terminal, never here: press open terminal on the sign-in card in the app's sources page"}
        return {"state": "ok", "detail": "signed in to telegram"} if await tg.get_me() else \
            {"state": "needs_you", "detail": "the code was not scanned in time. on your phone: telegram > settings > devices > link desktop device, then try again"}
    finally:
        await tg.disconnect()


def login(emit, stop=None, client=None, tries=TRIES, each=EACH):
    """client: (a telethon-like client, the error class that means a two-step password is wanted), for tests."""
    if client is None:
        tg, needs_password, why = _client()
        if why:
            return {"state": "cannot", "detail": why}
    else:
        tg, needs_password = client
    try:
        return asyncio.run(_login(tg, needs_password, emit, stop, tries, each))
    except Exception as e:
        return {"state": "cannot", "detail": "telegram did not answer: " + str(e).split(": ")[-1][:120]}
