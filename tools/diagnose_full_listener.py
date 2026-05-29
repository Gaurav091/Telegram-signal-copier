"""Run exact same flow as the real listener and log all exceptions."""
import asyncio
import traceback
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('listener_trace')

from telegram_signal_copier.config import AppConfig


async def _probe():
    from telethon import TelegramClient, events
    from telethon.sessions import SQLiteSession, StringSession

    cfg = AppConfig.from_env()
    session_dir = cfg.project_root / 'runtime' / 'sessions'
    session_name = str(session_dir / f'{cfg.telegram_session_name}-listener')

    sq = SQLiteSession(session_name)
    try:
        serialized = StringSession.save(sq)
    finally:
        sq.close()
    if not serialized:
        log.error('StringSession empty — not authorized')
        return

    client = TelegramClient(StringSession(serialized), int(cfg.telegram_api_id), cfg.telegram_api_hash)
    log.info('Calling client.start...')
    try:
        await client.start(phone=cfg.telegram_phone_number)
        log.info('client.start complete')
    except Exception as e:
        log.error('client.start FAILED: %s', traceback.format_exc())
        return

    log.info('Resolving sources...')
    sources = cfg.telegram_source_mappings
    resolved = []
    for label, ident in sources:
        try:
            raw_id = int(ident) if ident.isdigit() else None
            if raw_id:
                entity = None
                for attempt_id in (int(f'-100{ident}'), raw_id):
                    try:
                        entity = await client.get_entity(attempt_id)
                        break
                    except Exception:
                        continue
                if entity:
                    resolved.append(entity)
                    log.info('Resolved: %s', label)
                else:
                    log.warning('FAILED: %s (%s)', label, ident)
            else:
                entity = await client.get_entity(ident.lstrip('@'))
                resolved.append(entity)
                log.info('Resolved: %s', label)
        except Exception as e:
            log.warning('FAILED: %s (%s): %s', label, ident, e)

    log.info('Resolved %d / %d sources', len(resolved), len(sources))
    if not resolved:
        log.error('No sources resolved')
        await client.disconnect()
        return

    @client.on(events.NewMessage(chats=resolved))
    async def handler(event):
        chat = await event.get_chat()
        log.info('NEW MESSAGE from %s: %s', getattr(chat, 'title', '?'), str(event.raw_text)[:80])

    log.info('Running until disconnected (will run for 30s then stop)...')
    try:
        await asyncio.wait_for(client.run_until_disconnected(), timeout=30)
    except asyncio.TimeoutError:
        log.info('30s timeout reached — stopping cleanly')
    except Exception as e:
        log.error('run_until_disconnected error: %s', traceback.format_exc())
    finally:
        await client.disconnect()
        log.info('Disconnected')


if __name__ == '__main__':
    try:
        asyncio.run(_probe())
    except Exception:
        traceback.print_exc()
