"""
Haumea Clones — JSON-RPC Backend Server
Communicates with Electron via stdin/stdout JSON-RPC 2.0
"""
from __future__ import annotations

import sys
import json
import asyncio
import threading
import hashlib
import random
import tempfile
import os
import socket
import time
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, RPCError
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage,
    MessageMediaContact, MessageMediaGeo, MessageMediaPoll,
    MessageMediaGame, MessageMediaInvoice, MessageMediaGeoLive,
    MessageMediaVenue, MessageMediaDice, MessageMediaStory,
    DocumentAttributeSticker, DocumentAttributeVideo,
    DocumentAttributeAudio, DocumentAttributeAnimated,
    PeerChannel, InputPeerChannel,
    MessageMediaUnsupported, DocumentAttributeFilename
)
from telethon.tl.tlobject import TLRequest
from haumea_rpc import is_file_reference_error

# Forum topic support
try:
    from telethon.tl.functions.channels import CreateForumTopicRequest, GetForumTopicsRequest
    HAS_FORUM_TOPIC = True
except ImportError:
    HAS_FORUM_TOPIC = False
    # Fallback implementations kept from original main.py
    class CreateForumTopicRequest(TLRequest):
        CONSTRUCTOR_ID = 0xf40c0224
        SUBCLASS_OF_ID = 0x8af52aac

        def __init__(self, channel, title, random_id, icon_color=None, icon_emoji_id=None, send_as=None):
            self.channel = channel
            self.title = title
            self.random_id = random_id
            self.icon_color = icon_color
            self.icon_emoji_id = icon_emoji_id
            self.send_as = send_as

        def to_dict(self):
            return {
                '_': 'CreateForumTopicRequest',
                'channel': self.channel.to_dict() if hasattr(self.channel, 'to_dict') else self.channel,
                'title': self.title,
                'random_id': self.random_id,
                'icon_color': self.icon_color,
                'icon_emoji_id': self.icon_emoji_id,
                'send_as': self.send_as
            }

        def _bytes(self):
            import struct
            flags = 0
            if self.icon_color is not None: flags |= 1
            if self.send_as is not None: flags |= 4
            if self.icon_emoji_id is not None: flags |= 8

            result = struct.pack('<I', self.CONSTRUCTOR_ID)
            result += struct.pack('<I', flags)
            result += self.channel._bytes() if hasattr(self.channel, '_bytes') else bytes()
            title_bytes = self.title.encode('utf-8')
            if len(title_bytes) < 254:
                result += bytes([len(title_bytes)]) + title_bytes
            else:
                result += bytes([254]) + struct.pack('<I', len(title_bytes))[:3] + title_bytes
            padding = (4 - (len(title_bytes) + 1) % 4) % 4
            result += bytes(padding)
            if self.icon_color is not None:
                result += struct.pack('<i', self.icon_color)
            if self.icon_emoji_id is not None:
                result += struct.pack('<q', self.icon_emoji_id)
            result += struct.pack('<q', self.random_id)
            if self.send_as is not None:
                result += self.send_as._bytes() if hasattr(self.send_as, '_bytes') else bytes()
            return result

        @classmethod
        def from_reader(cls, reader):
            raise NotImplementedError()

    class GetForumTopicsRequest(TLRequest):
        CONSTRUCTOR_ID = 0x0de560d1
        SUBCLASS_OF_ID = 0x913da64f

        def __init__(self, channel, offset_date, offset_id, offset_topic, limit, q=None):
            self.channel = channel
            self.q = q
            self.offset_date = offset_date
            self.offset_id = offset_id
            self.offset_topic = offset_topic
            self.limit = limit

        def to_dict(self):
            return {
                '_': 'GetForumTopicsRequest',
                'channel': self.channel.to_dict() if hasattr(self.channel, 'to_dict') else self.channel,
                'q': self.q,
                'offset_date': self.offset_date,
                'offset_id': self.offset_id,
                'offset_topic': self.offset_topic,
                'limit': self.limit
            }

        def _bytes(self):
            import struct
            flags = 0
            if self.q is not None: flags |= 1

            result = struct.pack('<I', self.CONSTRUCTOR_ID)
            result += struct.pack('<I', flags)
            result += self.channel._bytes() if hasattr(self.channel, '_bytes') else bytes()
            if self.q is not None:
                q_bytes = self.q.encode('utf-8')
                if len(q_bytes) < 254:
                    result += bytes([len(q_bytes)]) + q_bytes
                else:
                    result += bytes([254]) + struct.pack('<I', len(q_bytes))[:3] + q_bytes
                padding = (4 - (len(q_bytes) + 1) % 4) % 4
                result += bytes(padding)
            result += struct.pack('<i', self.offset_date)
            result += struct.pack('<i', self.offset_id)
            result += struct.pack('<i', self.offset_topic)
            result += struct.pack('<i', self.limit)
            return result

        @classmethod
        def from_reader(cls, reader):
            raise NotImplementedError()

    HAS_FORUM_TOPIC = True


class HaumeaServer:
    """JSON-RPC server over stdin/stdout for Telegram operations."""

    def __init__(self):
        self.client = None
        self.logged_in = False
        self.loop = None
        self._dialogs_cached = False
        self.stop_flag = False
        self.skip_current_file = False
        self.progress_dir = Path("progress")
        self.progress_dir.mkdir(exist_ok=True)
        self._download_start_time = 0
        self._download_last_bytes = 0
        self.connect_timeout = 25

    # ── Notifications (push to Electron) ──

    def _notify(self, method, params):
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

    def log(self, message, tag="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._notify("log", {"time": ts, "message": message, "tag": tag})

    def emit_progress(self, data):
        self._notify("progress", data)

    def emit_status(self, status):
        self._notify("status", {"status": status})

    # ── JSON-RPC Request Handler ──

    def _respond(self, req_id, result=None, error=None):
        if error:
            msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": -1, "message": str(error)}})
        else:
            msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

    async def handle(self, req):
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        handler = getattr(self, f"rpc_{method}", None)
        if not handler:
            self._respond(req_id, error=f"Unknown method: {method}")
            return

        try:
            result = await handler(**params) if asyncio.iscoroutinefunction(handler) else handler(**params)
            self._respond(req_id, result=result or {"ok": True})
        except Exception as e:
            self._respond(req_id, error=str(e))

    # ── RPC Methods ──

    def rpc_ping(self):
        return {"pong": True}

    def rpc_shutdown(self):
        if self.client and self.loop:
            try:
                asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop)
            except Exception:
                pass
        sys.exit(0)

    def rpc_get_saved_progress(self):
        files = list(self.progress_dir.glob("clone_*.json"))
        results = []
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_file"] = str(f)
                results.append(data)
            except Exception:
                pass
        return {"progress_files": results}

    def rpc_delete_progress(self, file_path=""):
        p = Path(file_path)
        if p.exists():
            p.unlink()
        return {"ok": True}

    def rpc_load_config(self, path="config.json"):
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    def rpc_save_config(self, config=None, path="config.json"):
        if config:
            Path(path).write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}

    # ── Connection ──

    def _test_connection_latency(self):
        dc_ips_v4 = ["149.154.175.53", "149.154.167.51", "149.154.175.100"]
        dc_ips_v6 = ["2001:0b28:f23d:f001::a", "2001:067c:04e8:f002::a"]

        def test_ip(ip, port=443, family=socket.AF_INET):
            times = []
            for _ in range(3):
                try:
                    s = socket.socket(family, socket.SOCK_STREAM)
                    s.settimeout(3)
                    start = time.time()
                    s.connect((ip, port))
                    elapsed = (time.time() - start) * 1000
                    times.append(elapsed)
                    s.close()
                except Exception:
                    times.append(float('inf'))
            return sum(times) / len(times) if times else float('inf')

        avg_ipv4 = min((test_ip(ip) for ip in dc_ips_v4), default=float('inf'))
        avg_ipv6 = float('inf')
        try:
            avg_ipv6 = min((test_ip(ip, family=socket.AF_INET6) for ip in dc_ips_v6), default=float('inf'))
        except Exception:
            pass

        use_ipv6 = avg_ipv6 < avg_ipv4 and avg_ipv6 != float('inf')
        return use_ipv6, avg_ipv4, avg_ipv6

    async def _create_client(self, api_id, api_hash):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self.log("Testando latência IPv4 vs IPv6...", "info")
        use_ipv6, avg_ipv4, avg_ipv6 = self._test_connection_latency()

        ipv4_str = f"{avg_ipv4:.0f}ms" if avg_ipv4 != float('inf') else "N/A"
        ipv6_str = f"{avg_ipv6:.0f}ms" if avg_ipv6 != float('inf') else "N/A"
        protocol = "IPv6" if use_ipv6 else "IPv4"
        self.log(f"Latência: IPv4={ipv4_str}, IPv6={ipv6_str} → Usando {protocol}", "info")

        self.client = TelegramClient(
            "haumea_session", api_id, api_hash,
            timeout=self.connect_timeout,
            connection_retries=2,
            retry_delay=1,
            flood_sleep_threshold=120,
            use_ipv6=use_ipv6
        )
        try:
            await asyncio.wait_for(self.client.connect(), timeout=self.connect_timeout)
        except asyncio.TimeoutError:
            self.log("Timeout ao conectar no Telegram. Verifique rede, IPv4/IPv6 ou API ID/API Hash.", "error")
            self.emit_status("disconnected")
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
            raise RuntimeError("Timeout ao conectar no Telegram")
        except Exception:
            self.emit_status("disconnected")
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
            raise

    async def rpc_connect(self, api_id="", api_hash="", phone="", password=""):
        self.emit_status("connecting")
        api_id = int(api_id)
        await self._create_client(api_id, api_hash)

        if not await self.client.is_user_authorized():
            self.log("Enviando código de verificação...", "info")
            await self.client.send_code_request(phone)
            self.emit_status("awaiting_code")
            return {"ok": True, "needs_code": True}

        self.logged_in = True
        me = await self.client.get_me()
        name = me.first_name or ""
        username = f"(@{me.username})" if me.username else ""
        self.log(f"Conectado como: {name} {username}", "success")
        self.emit_status("connected")
        return {"ok": True, "needs_code": False, "user": {"name": name, "username": me.username}}

    async def rpc_submit_code(self, phone="", code="", password=""):
        try:
            await self.client.sign_in(phone, code)
        except SessionPasswordNeededError:
            if not password:
                self.emit_status("awaiting_2fa")
                return {"ok": True, "needs_2fa": True}
            await self.client.sign_in(password=password)

        self.logged_in = True
        me = await self.client.get_me()
        name = me.first_name or ""
        username = f"(@{me.username})" if me.username else ""
        self.log(f"Conectado como: {name} {username}", "success")
        self.emit_status("connected")
        return {"ok": True, "user": {"name": name, "username": me.username}}

    async def rpc_submit_2fa(self, password=""):
        await self.client.sign_in(password=password)
        self.logged_in = True
        me = await self.client.get_me()
        name = me.first_name or ""
        username = f"(@{me.username})" if me.username else ""
        self.log(f"Conectado como: {name} {username}", "success")
        self.emit_status("connected")
        return {"ok": True, "user": {"name": name, "username": me.username}}

    async def rpc_auto_login(self, api_id="", api_hash=""):
        session_file = Path("haumea_session.session")
        if not session_file.exists():
            self.emit_status("disconnected")
            return {"ok": False, "error": "No session file"}

        api_id = int(api_id)
        self.emit_status("connecting")
        await self._create_client(api_id, api_hash)

        if await self.client.is_user_authorized():
            self.logged_in = True
            me = await self.client.get_me()
            name = me.first_name or ""
            username = f"(@{me.username})" if me.username else ""
            self.log(f"Login automático: {name} {username}", "success")
            self.emit_status("connected")
            return {"ok": True, "user": {"name": name, "username": me.username}}
        else:
            await self.client.disconnect()
            self.client = None
            self.emit_status("disconnected")
            return {"ok": False, "error": "Session expired"}

    # ── Entity Resolution ──

    async def resolve_entity(self, identifier):
        identifier = str(identifier).strip()
        if not self._dialogs_cached:
            self.log("Carregando lista de chats...", "info")
            async for _ in self.client.iter_dialogs():
                pass
            self._dialogs_cached = True

        try:
            return await self.client.get_entity(identifier)
        except Exception:
            pass

        try:
            numeric_id = int(identifier)
            if numeric_id < 0:
                str_id = str(abs(numeric_id))
                if str_id.startswith("100") and len(str_id) > 10:
                    real_id = int(str_id[3:])
                    try:
                        peer = InputPeerChannel(channel_id=real_id, access_hash=0)
                        return await self.client.get_entity(peer)
                    except Exception:
                        pass
            try:
                peer = PeerChannel(abs(numeric_id))
                return await self.client.get_entity(peer)
            except Exception:
                pass
        except ValueError:
            pass

        if "t.me/" in identifier:
            username = identifier.split("t.me/")[-1].split("/")[0].split("?")[0]
            if username:
                try:
                    return await self.client.get_entity(username)
                except Exception:
                    pass

        if not identifier.startswith("@"):
            try:
                return await self.client.get_entity(f"@{identifier}")
            except Exception:
                pass

        raise ValueError(f"Não foi possível encontrar: {identifier}")

    def parse_target_identifier(self, identifier):
        raw = str(identifier).strip()
        normalized = raw.replace("https://", "").replace("http://", "").strip("/")

        if "t.me/" not in normalized:
            return {"entity": raw, "topic_id": None}

        path = normalized.split("t.me/")[-1].split("?")[0].strip("/")
        parts = [part for part in path.split("/") if part]

        if len(parts) >= 2 and parts[0] != "c" and parts[1].isdigit():
            return {"entity": parts[0], "topic_id": int(parts[1])}

        if len(parts) >= 3 and parts[0] == "c" and parts[1].isdigit() and parts[2].isdigit():
            return {"entity": f"-100{parts[1]}", "topic_id": int(parts[2])}

        return {"entity": raw, "topic_id": None}

    async def resolve_target(self, identifier):
        parsed = self.parse_target_identifier(identifier)
        entity = await self.resolve_entity(parsed["entity"])
        return entity, parsed["topic_id"]

    def get_iter_messages_kwargs(self, limit=0, reverse=False, reply_to=None, min_id=None):
        kwargs = {
            "limit": None if limit == 0 else limit,
            "reverse": reverse,
        }
        if reply_to:
            kwargs["reply_to"] = reply_to
        if min_id:
            kwargs["min_id"] = min_id
        return kwargs

    # ── Media Helpers ──

    def get_media_type(self, message):
        if not message.media:
            return "texto"
        media = message.media
        if isinstance(media, MessageMediaPhoto):
            return "foto"
        elif isinstance(media, MessageMediaDocument):
            if media.document:
                for attr in media.document.attributes:
                    if isinstance(attr, DocumentAttributeSticker):
                        return "sticker"
                    if isinstance(attr, DocumentAttributeAnimated):
                        return "GIF"
                    if isinstance(attr, DocumentAttributeVideo):
                        return "vídeo circular" if attr.round_message else "vídeo"
                    if isinstance(attr, DocumentAttributeAudio):
                        return "msg de voz" if attr.voice else "áudio"
            return "documento"
        elif isinstance(media, MessageMediaWebPage):
            return "link"
        elif isinstance(media, MessageMediaContact):
            return "contato"
        elif isinstance(media, (MessageMediaGeo, MessageMediaGeoLive, MessageMediaVenue)):
            return "localização"
        elif isinstance(media, MessageMediaPoll):
            return "enquete"
        elif isinstance(media, MessageMediaDice):
            return media.emoticon if media.emoticon else "dado"
        elif isinstance(media, MessageMediaGame):
            return "jogo"
        elif isinstance(media, MessageMediaInvoice):
            return "fatura"
        elif isinstance(media, MessageMediaStory):
            return "story"
        elif isinstance(media, MessageMediaUnsupported):
            return "não suportado"
        return "mídia"

    def _is_visual_media(self, media):
        if isinstance(media, MessageMediaPhoto):
            return True
        if isinstance(media, MessageMediaDocument) and media.document:
            for attr in media.document.attributes:
                if isinstance(attr, (DocumentAttributeVideo, DocumentAttributeAnimated, DocumentAttributeSticker)):
                    return True
        return False

    async def _send_message_like_main(self, dest_entity, msg, reply_to=None):
        kwargs = {}
        if reply_to:
            kwargs["reply_to"] = reply_to

        if msg.media:
            if isinstance(msg.media, MessageMediaWebPage):
                if msg.message:
                    await self.client.send_message(
                        dest_entity,
                        msg.message,
                        formatting_entities=msg.entities,
                        parse_mode=None,
                        **kwargs,
                    )
                    return True
                return False

            if isinstance(msg.media, (MessageMediaPoll, MessageMediaContact, MessageMediaGeo,
                                      MessageMediaGeoLive, MessageMediaVenue, MessageMediaDice)):
                await self.client.send_message(dest_entity, file=msg.media, **kwargs)
                return True

            if isinstance(msg.media, (MessageMediaGame, MessageMediaInvoice, MessageMediaUnsupported)):
                if msg.message:
                    await self.client.send_message(
                        dest_entity,
                        msg.message,
                        formatting_entities=msg.entities,
                        parse_mode=None,
                        **kwargs,
                    )
                    return True
                return False

            await self.client.send_file(
                dest_entity,
                msg.media,
                caption=msg.message or "",
                formatting_entities=msg.entities,
                parse_mode=None,
                force_document=isinstance(msg.media, MessageMediaDocument) and not self._is_visual_media(msg.media),
                **kwargs,
            )
            return True

        if msg.message:
            await self.client.send_message(
                dest_entity,
                msg.message,
                formatting_entities=msg.entities,
                parse_mode=None,
                **kwargs,
            )
            return True

        return False

    async def _send_downloaded_media_like_main(self, dest_entity, file_path, msg, reply_to=None,
                                               progress_callback=None, original_filename=None):
        kwargs = {
            "caption": msg.message or "",
            "formatting_entities": msg.entities,
            "parse_mode": None,
        }
        if reply_to:
            kwargs["reply_to"] = reply_to

        is_visual = self._is_visual_media(msg.media)
        file_attributes = None
        if original_filename and not is_visual:
            file_attributes = [DocumentAttributeFilename(file_name=original_filename)]

        await self.client.send_file(
            dest_entity,
            file_path,
            force_document=not is_visual,
            attributes=file_attributes,
            progress_callback=progress_callback,
            **kwargs,
        )

    def _format_bytes(self, bytes_value):
        if bytes_value < 1024: return f"{bytes_value} B"
        elif bytes_value < 1024 * 1024: return f"{bytes_value/1024:.1f} KB"
        elif bytes_value < 1024 * 1024 * 1024: return f"{bytes_value/(1024*1024):.1f} MB"
        else: return f"{bytes_value/(1024*1024*1024):.2f} GB"

    def _format_speed(self, bps):
        if bps < 1024: return f"{bps:.0f} B/s"
        elif bps < 1024*1024: return f"{bps/1024:.1f} KB/s"
        else: return f"{bps/(1024*1024):.1f} MB/s"

    def _format_eta(self, seconds):
        if seconds <= 0 or seconds == float('inf'): return "calculando..."
        if seconds < 60: return f"{seconds:.0f}s"
        elif seconds < 3600: return f"{seconds//60:.0f}m {seconds%60:.0f}s"
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h:.0f}h {m:.0f}m"

    # ── Progress save/load ──

    def get_progress_filename(self, source, dest):
        key = f"{source}_{dest}"
        hash_key = hashlib.md5(key.encode()).hexdigest()[:12]
        return self.progress_dir / f"clone_{hash_key}.json"

    def save_progress(self, source, dest, last_msg_id, cloned, total, source_title, dest_title):
        pf = self.get_progress_filename(source, dest)
        data = {
            "source": source, "dest": dest,
            "source_title": source_title, "dest_title": dest_title,
            "last_message_id": last_msg_id, "cloned": cloned, "total": total,
            "timestamp": datetime.now().isoformat(),
        }
        pf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete_progress_file(self, source, dest):
        pf = self.get_progress_filename(source, dest)
        if pf.exists():
            pf.unlink()

    # ── Clone Operations ──

    async def rpc_clone(self, source="", dest="", limit=0, delay=0.1,
                        pause_every=50, pause_duration=2, resume_from_msg_id=None):
        if not self.logged_in:
            raise Exception("Não conectado ao Telegram")

        self.stop_flag = False
        self._dialogs_cached = False
        self.emit_progress({"type": "clone", "status": "starting"})
        self.log("Resolvendo entidades...", "info")

        source_entity, source_topic_id = await self.resolve_target(source)
        dest_entity, dest_topic_id = await self.resolve_target(dest)

        source_title = getattr(source_entity, 'title', str(source))
        dest_title = getattr(dest_entity, 'title', str(dest))
        if source_topic_id:
            source_title = f"{source_title} > tópico {source_topic_id}"
        if dest_topic_id:
            dest_title = f"{dest_title} > tópico {dest_topic_id}"
        self.log(f"Origem: {source_title}", "info")
        self.log(f"Destino: {dest_title}", "info")

        # Count messages
        total = 0
        async for _ in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(limit=limit, reply_to=source_topic_id)
        ):
            total += 1
        self.log(f"Total de mensagens: {total}", "info")

        if total == 0:
            self.log("Nenhuma mensagem encontrada!", "warning")
            self.emit_progress({"type": "clone", "status": "done", "cloned": 0, "total": 0})
            return {"ok": True, "cloned": 0}

        # Collect messages (oldest first)
        messages = []
        async for msg in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(
                limit=limit,
                reverse=True,
                reply_to=source_topic_id,
                min_id=resume_from_msg_id if resume_from_msg_id else None,
            )
        ):
            messages.append(msg)

        cloned = 0
        errors = 0
        for i, msg in enumerate(messages):
            if self.stop_flag:
                self.log("Clonagem interrompida!", "warning")
                self.save_progress(source, dest, msg.id, cloned, total, source_title, dest_title)
                break

            try:
                media_type = self.get_media_type(msg)

                sent = await self._send_message_like_main(dest_entity, msg, reply_to=dest_topic_id)
                if not sent:
                    cloned += 1
                    continue

                cloned += 1
                pct = int((cloned / total) * 100) if total else 0
                self.emit_progress({
                    "type": "clone", "status": "running",
                    "cloned": cloned, "total": total, "percent": pct,
                    "media_type": media_type,
                })

                if cloned % 10 == 0:
                    self.log(f"Progresso: {cloned}/{total} ({pct}%)", "info")
                    self.save_progress(source, dest, msg.id, cloned, total, source_title, dest_title)

                if pause_every > 0 and cloned % pause_every == 0:
                    self.log(f"Anti-flood: pausando {pause_duration}s...", "warning")
                    await asyncio.sleep(pause_duration)

                await asyncio.sleep(delay)

            except FloodWaitError as e:
                wait = e.seconds + 5
                self.log(f"FloodWait: aguardando {wait}s...", "error")
                self.save_progress(source, dest, msg.id, cloned, total, source_title, dest_title)
                await asyncio.sleep(wait)
            except Exception as e:
                if is_file_reference_error(e):
                    try:
                        refreshed = await self.client.get_messages(source_entity, ids=[msg.id])
                        if refreshed and refreshed[0]:
                            rmsg = refreshed[0]
                            if await self._send_message_like_main(dest_entity, rmsg, reply_to=dest_topic_id):
                                cloned += 1
                                continue
                    except Exception:
                        pass
                errors += 1
                self.log(f"Erro msg #{msg.id}: {e}", "error")

        self.delete_progress_file(source, dest)
        self.log(f"Clonagem concluída! {cloned}/{total} mensagens, {errors} erros", "success")
        self.emit_progress({"type": "clone", "status": "done", "cloned": cloned, "total": total, "errors": errors})
        return {"ok": True, "cloned": cloned, "total": total, "errors": errors}

    async def rpc_stop(self):
        self.stop_flag = True
        self.log("Parando clonagem...", "warning")
        return {"ok": True}

    async def rpc_skip_download(self):
        self.skip_current_file = True
        self.log("Pulando arquivo atual...", "warning")
        return {"ok": True}

    # ── Multi-Group Clone ──

    async def create_forum_topic(self, channel, title):
        try:
            result = await self.client(CreateForumTopicRequest(
                channel=channel,
                title=title,
                random_id=random.randint(1, 2**63 - 1),
            ))
            if hasattr(result, 'updates'):
                for update in result.updates:
                    if hasattr(update, 'message') and hasattr(update.message, 'reply_to'):
                        if hasattr(update.message.reply_to, 'reply_to_top_id'):
                            return update.message.reply_to.reply_to_top_id
                        elif hasattr(update.message.reply_to, 'reply_to_msg_id'):
                            return update.message.reply_to.reply_to_msg_id
            if hasattr(result, 'updates'):
                for update in result.updates:
                    if hasattr(update, 'id'):
                        return update.id
        except Exception as e:
            self.log(f"Erro ao criar tópico '{title}': {e}", "error")
            raise

    async def clone_to_topic(self, source_entity, dest_entity, topic_id, limit, delay,
                             pause_every, pause_duration, source_title, source_topic_id=None):
        messages = []
        async for msg in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(limit=limit, reverse=True, reply_to=source_topic_id)
        ):
            messages.append(msg)

        total = len(messages)
        cloned = 0
        self.log(f"Clonando {total} msgs de '{source_title}' para tópico...", "info")

        for i, msg in enumerate(messages):
            if self.stop_flag:
                break
            try:
                if not await self._send_message_like_main(dest_entity, msg, reply_to=topic_id):
                    cloned += 1
                    continue

                cloned += 1
                if pause_every > 0 and cloned % pause_every == 0:
                    self.log(f"Anti-flood: pausando {pause_duration}s...", "warning")
                    await asyncio.sleep(pause_duration)
                await asyncio.sleep(delay)
            except FloodWaitError as e:
                self.log(f"FloodWait: aguardando {e.seconds + 5}s...", "error")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                self.log(f"Erro msg #{msg.id}: {e}", "error")

        self.log(f"'{source_title}' concluído: {cloned}/{total}", "success")
        return cloned

    async def rpc_multi_clone(self, sources=None, dest="", limit=0, delay=0.1,
                              pause_every=50, pause_duration=2):
        if not self.logged_in:
            raise Exception("Não conectado")
        if not sources:
            raise Exception("Nenhum grupo de origem")

        self.stop_flag = False
        self._dialogs_cached = False
        dest_entity, _dest_topic_id = await self.resolve_target(dest)
        total_groups = len(sources)

        for idx, src in enumerate(sources):
            if self.stop_flag:
                break
            src = src.strip()
            if not src:
                continue

            self.log(f"Grupo {idx+1}/{total_groups}: {src}", "info")
            self.emit_progress({"type": "multi", "group_index": idx, "total_groups": total_groups})

            try:
                source_entity, source_topic_id = await self.resolve_target(src)
                source_title = getattr(source_entity, 'title', str(src))
                if source_topic_id:
                    source_title = f"{source_title} > tópico {source_topic_id}"
                topic_id = await self.create_forum_topic(dest_entity, source_title)
                self.log(f"Tópico criado: '{source_title}' (ID: {topic_id})", "success")
                await self.clone_to_topic(source_entity, dest_entity, topic_id,
                                          limit, delay, pause_every, pause_duration, source_title, source_topic_id)
            except Exception as e:
                self.log(f"Erro no grupo '{src}': {e}", "error")

        self.log("Multi-clone concluído!", "success")
        self.emit_progress({"type": "multi", "status": "done"})
        return {"ok": True}

    # ── Forum Clone ──

    async def get_forum_topics(self, entity):
        topics = []
        try:
            result = await self.client(GetForumTopicsRequest(
                channel=entity, offset_date=0, offset_id=0, offset_topic=0, limit=100
            ))
            if hasattr(result, 'topics'):
                for t in result.topics:
                    if hasattr(t, 'id') and hasattr(t, 'title'):
                        if t.id != 1:  # Skip General topic
                            topics.append({"id": t.id, "title": t.title})
        except Exception as e:
            self.log(f"Erro ao obter tópicos: {e}", "error")
        return topics

    async def clone_topic_messages(self, source_entity, source_topic_id, dest_entity,
                                    dest_topic_id, limit, delay, pause_every, pause_duration, topic_title):
        messages = []
        async for msg in self.client.iter_messages(
            source_entity, limit=None if limit == 0 else limit,
            reply_to=source_topic_id, reverse=True
        ):
            messages.append(msg)

        total = len(messages)
        cloned = 0
        self.log(f"Clonando {total} msgs do tópico '{topic_title}'...", "info")

        for i, msg in enumerate(messages):
            if self.stop_flag:
                break
            try:
                if not await self._send_message_like_main(dest_entity, msg, reply_to=dest_topic_id):
                    cloned += 1
                    continue

                cloned += 1
                if pause_every > 0 and cloned % pause_every == 0:
                    await asyncio.sleep(pause_duration)
                await asyncio.sleep(delay)
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                self.log(f"Erro msg #{msg.id}: {e}", "error")

        return cloned

    async def rpc_forum_clone(self, source="", dest="", limit=0, delay=0.1,
                              pause_every=50, pause_duration=2):
        if not self.logged_in:
            raise Exception("Não conectado")

        self.stop_flag = False
        self._dialogs_cached = False

        source_entity, source_topic_id = await self.resolve_target(source)
        dest_entity, _dest_topic_id = await self.resolve_target(dest)

        if source_topic_id:
            source_topics = [{"id": source_topic_id, "title": f"Tópico {source_topic_id}"}]
        else:
            source_topics = await self.get_forum_topics(source_entity)
        total_topics = len(source_topics)
        self.log(f"Encontrados {total_topics} tópicos no fórum de origem", "info")

        for idx, topic in enumerate(source_topics):
            if self.stop_flag:
                break

            self.log(f"Tópico {idx+1}/{total_topics}: {topic['title']}", "info")
            self.emit_progress({
                "type": "forum", "topic_index": idx, "total_topics": total_topics,
                "topic_title": topic['title']
            })

            try:
                new_topic_id = await self.create_forum_topic(dest_entity, topic['title'])
                self.log(f"Tópico criado: '{topic['title']}' (ID: {new_topic_id})", "success")
                await self.clone_topic_messages(
                    source_entity, topic['id'], dest_entity, new_topic_id,
                    limit, delay, pause_every, pause_duration, topic['title']
                )
            except Exception as e:
                self.log(f"Erro no tópico '{topic['title']}': {e}", "error")

        self.log("Clonagem de fórum concluída!", "success")
        self.emit_progress({"type": "forum", "status": "done"})
        return {"ok": True}

    # ── Restricted Clone ──

    async def rpc_restricted_clone(self, source="", dest="", limit=0, delay=0.1,
                                    pause_every=50, pause_duration=2, topic_id=None):
        if not self.logged_in:
            raise Exception("Não conectado")

        self.stop_flag = False
        self.skip_current_file = False
        self._dialogs_cached = False

        source_entity, source_topic_id = await self.resolve_target(source)
        dest_entity, dest_topic_id = await self.resolve_target(dest)
        source_title = getattr(source_entity, 'title', str(source))
        dest_title = getattr(dest_entity, 'title', str(dest))
        if source_topic_id:
            source_title = f"{source_title} > tópico {source_topic_id}"
        if dest_topic_id:
            dest_title = f"{dest_title} > tópico {dest_topic_id}"
        self.log(f"Origem restrita: {source_title}", "info")
        self.log(f"Destino: {dest_title}", "info")

        # Count messages
        total = 0
        async for _ in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(limit=limit, reply_to=source_topic_id)
        ):
            total += 1
        self.log(f"Total: {total} mensagens", "info")

        messages = []
        async for msg in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(limit=limit, reverse=True, reply_to=source_topic_id)
        ):
            messages.append(msg)

        cloned = 0
        downloaded = 0
        errors = 0
        self._download_start_time = time.time()

        for i, msg in enumerate(messages):
            if self.stop_flag:
                self.log("Clonagem restrita interrompida!", "warning")
                break

            try:
                media_type = self.get_media_type(msg)
                reply_to = topic_id if topic_id else dest_topic_id

                if msg.media and not isinstance(msg.media, (MessageMediaWebPage, MessageMediaPoll,
                                                             MessageMediaDice, MessageMediaContact,
                                                             MessageMediaGeo, MessageMediaGeoLive,
                                                             MessageMediaVenue)):
                    # Download to temp file
                    self.skip_current_file = False
                    file_ext = ".bin"
                    original_filename = None
                    if isinstance(msg.media, MessageMediaPhoto):
                        file_ext = ".jpg"
                    elif isinstance(msg.media, MessageMediaDocument) and msg.media.document:
                        for attr in msg.media.document.attributes:
                            if isinstance(attr, DocumentAttributeFilename):
                                original_filename = attr.file_name
                                file_ext = os.path.splitext(attr.file_name)[1] or file_ext
                                break

                    total_size = 0
                    if isinstance(msg.media, MessageMediaDocument) and msg.media.document:
                        total_size = msg.media.document.size or 0

                    filename = f"msg_{msg.id}{file_ext}"
                    self.emit_progress({
                        "type": "restricted", "status": "downloading",
                        "cloned": cloned, "total": total, "filename": filename,
                        "file_size": total_size,
                    })

                    def make_progress_cb(fn, ts):
                        def cb(current, total_bytes):
                            if self.skip_current_file:
                                raise Exception("SKIP_FILE")
                            elapsed = time.time() - self._download_start_time
                            speed = current / elapsed if elapsed > 0 else 0
                            eta = (ts - current) / speed if speed > 0 else 0
                            self.emit_progress({
                                "type": "download",
                                "current": current, "total": total_bytes or ts,
                                "speed": self._format_speed(speed),
                                "eta": self._format_eta(eta),
                                "filename": fn,
                                "percent": int((current / (total_bytes or ts)) * 100) if (total_bytes or ts) > 0 else 0,
                            })
                        return cb

                    with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
                        tmp_path = tmp.name

                    try:
                        self._download_start_time = time.time()
                        await msg.download_media(
                            file=tmp_path,
                            progress_callback=make_progress_cb(filename, total_size)
                        )
                        downloaded += 1

                        # Upload to destination
                        def make_upload_cb(fn, ts):
                            def cb(current, total_bytes):
                                self.emit_progress({
                                    "type": "upload",
                                    "current": current, "total": total_bytes or ts,
                                    "filename": fn,
                                    "percent": int((current / (total_bytes or ts)) * 100) if (total_bytes or ts) > 0 else 0,
                                })
                            return cb

                        await self._send_downloaded_media_like_main(
                            dest_entity,
                            tmp_path,
                            msg,
                            reply_to=reply_to,
                            progress_callback=make_upload_cb(filename, total_size),
                            original_filename=original_filename,
                        )
                    except Exception as exc:
                        if "SKIP_FILE" in str(exc):
                            self.log(f"Arquivo pulado: {filename}", "warning")
                        else:
                            raise
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass

                elif isinstance(msg.media, MessageMediaPoll):
                    kwargs = {'reply_to': topic_id} if topic_id else {}
                    await self.client.send_message(dest_entity, file=msg.media, **kwargs)
                elif isinstance(msg.media, MessageMediaDice):
                    kwargs = {'reply_to': topic_id} if topic_id else {}
                    await self.client.send_message(dest_entity, file=msg.media, **kwargs)
                elif msg.media or msg.message:
                    if not await self._send_message_like_main(dest_entity, msg, reply_to=reply_to):
                        cloned += 1
                        continue
                else:
                    cloned += 1
                    continue

                cloned += 1
                pct = int((cloned / total) * 100) if total else 0
                self.emit_progress({
                    "type": "restricted", "status": "running",
                    "cloned": cloned, "total": total, "percent": pct,
                    "downloaded": downloaded, "errors": errors,
                })

                if pause_every > 0 and cloned % pause_every == 0:
                    self.log(f"Anti-flood: pausando {pause_duration}s...", "warning")
                    await asyncio.sleep(pause_duration)

                await asyncio.sleep(delay)

            except FloodWaitError as e:
                wait = e.seconds + 5
                self.log(f"FloodWait: aguardando {wait}s...", "error")
                await asyncio.sleep(wait)
            except Exception as e:
                if "SKIP_FILE" not in str(e):
                    errors += 1
                    self.log(f"Erro msg #{msg.id}: {e}", "error")

        self.log(f"Clonagem restrita concluída! {cloned}/{total}, baixados: {downloaded}, erros: {errors}", "success")
        self.emit_progress({
            "type": "restricted", "status": "done",
            "cloned": cloned, "total": total, "downloaded": downloaded, "errors": errors,
        })
        return {"ok": True, "cloned": cloned, "total": total, "downloaded": downloaded, "errors": errors}


# ── Main Loop ──

async def main():
    server = HaumeaServer()

    if sys.stdin.isatty():
        print(
            "Haumea backend espera JSON-RPC via stdin e deve ser iniciado pelo Electron. "
            "Use `npm run dev` na raiz do projeto.",
            flush=True,
        )
        return

    while True:
        try:
            line = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not line:
                break
            line = line.decode('utf-8').strip()
            if not line:
                continue
            req = json.loads(line)
            # Handle in background to not block stdin reading
            asyncio.create_task(server.handle(req))
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -1, "message": str(e)}}),
                  flush=True)


if __name__ == "__main__":
    asyncio.run(main())
