"""
Haumea Clones — JSON-RPC Backend Server
Communicates with Electron via stdin/stdout JSON-RPC 2.0
"""
from __future__ import annotations

import sys
import json
import io
import asyncio
import threading
import hashlib
import mimetypes
import random
import os
import time
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, RPCError
from telethon.sessions import StringSession
from telethon.tl import functions
from telethon.utils import get_input_channel
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage,
    MessageMediaContact, MessageMediaGeo, MessageMediaPoll,
    MessageMediaGame, MessageMediaInvoice, MessageMediaGeoLive,
    MessageMediaVenue, MessageMediaDice, MessageMediaStory,
    DocumentAttributeSticker, DocumentAttributeVideo,
    DocumentAttributeAudio, DocumentAttributeAnimated,
    PeerChannel, InputPeerChannel, InputChannel,
    Channel, ChannelForbidden,
    MessageActionTopicCreate, MessageActionTopicEdit,
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
        self.progress_dir = Path("progress")
        self.progress_dir.mkdir(exist_ok=True)
        self.history_dir = Path("history")
        self.history_dir.mkdir(exist_ok=True)
        self.state_dir = Path("state")
        self.state_dir.mkdir(exist_ok=True)
        self.config_file = self.state_dir / "config.json"
        self.session_name = "haumea_session"
        self.session_base_path = self.state_dir.resolve() / self.session_name
        self.history_file = self.history_dir / "jobs.jsonl"
        self.error_file = self.history_dir / "errors.json"
        self.error_index = self._load_json_file(self.error_file, {})
        self.runtime_state = {
            "active_job": None,
            "last_job": None,
        }
        self.sync_task = None
        self.sync_state = {
            "active": False,
            "source": "",
            "dest": "",
            "source_title": "",
            "dest_title": "",
            "processed": 0,
            "media_files": 0,
            "ram_bypass_used": 0,
            "copy_message_used": 0,
            "skipped_duplicates": 0,
            "errors": 0,
            "poll_interval": 15,
            "delay": 0.2,
            "last_seen_id": 0,
            "started_at": None,
            "last_poll_at": None,
        }
        self.connect_timeout = 25
        self._last_send_used_ram_bypass = False
        self._last_send_used_copy_message = False

    # ── Notifications (push to Electron) ──

    def _notify(self, method, params):
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

    def log(self, message, tag="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._notify("log", {"time": ts, "message": message, "tag": tag})

    def _log_scope(self, scope, message, tag="info"):
        labels = {
            "clone": "CLONE",
            "sync": "SYNC",
            "multi": "MULTI",
            "forum": "FORUM",
            "topic": "TOPIC",
            "copy": "COPY",
            "ram": "RAM",
            "retry": "RETRY",
        }
        prefix = labels.get(scope, str(scope).upper())
        self.log(f"[{prefix}] {message}", tag)

    def _log_route_summary(self, scope, copy_message_used=0, ram_bypass_used=0, tag="info"):
        self._log_scope(
            scope,
            f"Rotas usadas | copy_message: {copy_message_used} | bypass RAM: {ram_bypass_used}",
            tag,
        )

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

    async def rpc_shutdown(self):
        if self.sync_task:
            self.sync_task.cancel()
            self.sync_task = None
        await self._dispose_client()
        return {"ok": True}

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
        results.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return {"progress_files": results}

    def rpc_delete_progress(self, file_path=""):
        p = Path(file_path)
        if p.exists():
            p.unlink()
        return {"ok": True}

    def _get_config_paths(self, path="config.json"):
        if path and path != "config.json":
            return [Path(path)]

        paths = [self.config_file]
        legacy_path = Path("config.json")
        if legacy_path != self.config_file:
            paths.append(legacy_path)
        return paths

    def rpc_load_config(self, path="config.json"):
        for candidate in self._get_config_paths(path):
            if candidate.exists():
                return json.loads(candidate.read_text(encoding="utf-8"))
        return {}

    def rpc_save_config(self, config=None, path="config.json"):
        if config is not None:
            target = self._get_config_paths(path)[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}

    def _load_json_file(self, path, fallback):
        try:
            p = Path(path)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return fallback

    def _save_json_file(self, path, data):
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _to_positive_int(self, value, fallback):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed > 0 else fallback

    def _to_positive_float(self, value, fallback):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed > 0 else fallback

    def _resolve_anti_flood_config(
        self,
        pause_every=50,
        pause_duration=2,
        pause_every_min=None,
        pause_every_max=None,
        pause_duration_min=None,
        pause_duration_max=None,
    ):
        max_every_seed = pause_every_max if pause_every_max is not None else pause_every
        max_duration_seed = pause_duration_max if pause_duration_max is not None else pause_duration
        enabled = self._to_positive_int(max_every_seed, 0) > 0 and self._to_positive_float(max_duration_seed, 0) > 0

        if not enabled:
            return {
                "enabled": False,
                "every_min": 0,
                "every_max": 0,
                "duration_min": 0,
                "duration_max": 0,
            }

        legacy_every = self._to_positive_int(pause_every, 50)
        every_min = self._to_positive_int(pause_every_min, legacy_every)
        every_max = self._to_positive_int(pause_every_max, legacy_every)
        legacy_duration = self._to_positive_float(pause_duration, 2)
        duration_min = self._to_positive_float(pause_duration_min, legacy_duration)
        duration_max = self._to_positive_float(pause_duration_max, legacy_duration)

        return {
            "enabled": True,
            "every_min": min(every_min, every_max),
            "every_max": max(every_min, every_max),
            "duration_min": min(duration_min, duration_max),
            "duration_max": max(duration_min, duration_max),
        }

    def _next_anti_flood_cycle(self, anti_flood, processed_so_far=0):
        if not anti_flood.get("enabled"):
            return None

        frequency = random.randint(anti_flood["every_min"], anti_flood["every_max"])
        duration = round(random.uniform(anti_flood["duration_min"], anti_flood["duration_max"]), 2)
        return {
            "after_messages": processed_so_far + frequency,
            "frequency": frequency,
            "duration": duration,
        }

    def _format_seconds(self, value):
        return f"{value:.2f}".rstrip("0").rstrip(".")

    def _pair_hash(self, source, dest, prefix="pair"):
        raw = f"{prefix}:{source}:{dest}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    def _build_runtime_metrics(self, started_at, processed, total):
        elapsed_seconds = max(1, int(time.time() - started_at))
        rate_per_minute = round((processed / elapsed_seconds) * 60, 2) if processed else 0
        remaining = max(total - processed, 0)
        eta_seconds = int((remaining / (rate_per_minute / 60))) if rate_per_minute > 0 else None
        return {
            "elapsed_seconds": elapsed_seconds,
            "messages_per_minute": rate_per_minute,
            "eta_seconds": eta_seconds,
            "eta_label": self._format_eta(eta_seconds) if eta_seconds is not None else "calculando...",
        }

    def _set_active_job(self, operation, payload):
        self.runtime_state["active_job"] = {
            "operation": operation,
            **payload,
            "updated_at": datetime.now().isoformat(),
        }

    def _finish_active_job(self, payload):
        finished = {
            **(self.runtime_state.get("active_job") or {}),
            **payload,
            "updated_at": datetime.now().isoformat(),
        }
        self.runtime_state["last_job"] = finished
        self.runtime_state["active_job"] = None

    def _append_history_entry(self, entry):
        line = json.dumps(entry, ensure_ascii=False)
        with self.history_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _read_history_entries(self, limit=50):
        if not self.history_file.exists():
            return []
        try:
            lines = self.history_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []

        items = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
            if len(items) >= limit:
                break
        return items

    def _create_history_entry(self, operation, status, source, dest, source_title, dest_title, started_at, **metrics):
        finished_at = datetime.now().isoformat()
        duration_seconds = 0
        if started_at:
            try:
                started_ts = datetime.fromisoformat(started_at).timestamp()
                duration_seconds = max(0, int(time.time() - started_ts))
            except Exception:
                duration_seconds = 0
        return {
            "operation": operation,
            "status": status,
            "source": source,
            "dest": dest,
            "source_title": source_title,
            "dest_title": dest_title,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            **metrics,
        }

    def rpc_get_history(self, limit=40):
        entries = self._read_history_entries(limit=int(limit or 40))
        return {"entries": entries}

    def rpc_clear_history(self):
        if self.history_file.exists():
            self.history_file.unlink()
        return {"ok": True}

    def _classify_error(self, exc):
        message = str(exc)
        lowered = message.lower()

        if isinstance(exc, FloodWaitError) or "floodwait" in lowered:
            return {
                "category": "flood_wait",
                "title": "Flood wait detectado",
                "action": "Aumente a pausa, reduza a taxa de envio ou retome mais tarde.",
            }
        if "não foi possível encontrar" in lowered or "username" in lowered or "cannot find" in lowered:
            return {
                "category": "entity_resolution",
                "title": "Origem ou destino não resolvido",
                "action": "Confira @username, link t.me ou ID numérico antes de reenviar.",
            }
        if "forbidden" in lowered or "permission" in lowered or "admin" in lowered:
            return {
                "category": "permissions",
                "title": "Permissão insuficiente",
                "action": "Verifique se a conta pode postar, criar tópicos ou acessar o chat.",
            }
        if "reply_to" in lowered or "topic" in lowered:
            return {
                "category": "topics",
                "title": "Falha de tópico ou roteamento",
                "action": "Revise o ID do tópico e se o destino realmente é fórum.",
            }
        if is_file_reference_error(exc) or "file reference" in lowered:
            return {
                "category": "media_reference",
                "title": "Referência de mídia expirada",
                "action": "Recarregue a mensagem; o reenvio tenta renovar a referência e aplicar o bypass em RAM automaticamente.",
            }
        if "timeout" in lowered or "timed out" in lowered or "network" in lowered:
            return {
                "category": "network",
                "title": "Instabilidade de rede",
                "action": "Valide a conexão e tente novamente com delays maiores.",
            }
        if "password" in lowered or "authorized" in lowered or "session" in lowered:
            return {
                "category": "session",
                "title": "Problema de sessão",
                "action": "Reconecte a conta e confira a autenticação em duas etapas.",
            }
        return {
            "category": "unknown",
            "title": "Erro não classificado",
            "action": "Revise o log detalhado e repita o job com lote menor para isolar a falha.",
        }

    def _record_error(self, exc, operation, context=None):
        classification = self._classify_error(exc)
        key = f"{operation}:{classification['category']}:{classification['title']}"
        existing = self.error_index.get(key, {
            "key": key,
            "operation": operation,
            "category": classification["category"],
            "title": classification["title"],
            "action": classification["action"],
            "count": 0,
            "last_message": "",
            "last_context": {},
            "last_seen": None,
        })
        existing["count"] += 1
        existing["last_message"] = str(exc)
        existing["last_context"] = context or {}
        existing["last_seen"] = datetime.now().isoformat()
        self.error_index[key] = existing
        self._save_json_file(self.error_file, self.error_index)

    def rpc_get_error_summary(self):
        items = sorted(
            self.error_index.values(),
            key=lambda item: (item.get("count", 0), item.get("last_seen") or ""),
            reverse=True,
        )
        return {"items": items[:20]}

    def rpc_clear_error_summary(self):
        self.error_index = {}
        self._save_json_file(self.error_file, self.error_index)
        return {"ok": True}

    def get_dedupe_filename(self, source, dest):
        hash_key = self._pair_hash(source, dest, prefix="dedupe")
        return self.state_dir / f"dedupe_{hash_key}.json"

    def load_dedupe_state(self, source, dest):
        return self._load_json_file(
            self.get_dedupe_filename(source, dest),
            {"message_ids": [], "fingerprints": [], "updated_at": None},
        )

    def save_dedupe_state(self, source, dest, state):
        normalized = {
            "message_ids": list(state.get("message_ids", []))[-20000:],
            "fingerprints": list(state.get("fingerprints", []))[-20000:],
            "updated_at": datetime.now().isoformat(),
        }
        self._save_json_file(self.get_dedupe_filename(source, dest), normalized)
        return normalized

    def get_message_fingerprint(self, msg):
        payload = {
            "text": msg.message or "",
            "media_type": self.get_media_type(msg),
            "reply_to": getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None),
            "date": msg.date.isoformat() if getattr(msg, "date", None) else None,
        }
        if isinstance(msg.media, MessageMediaDocument) and msg.media.document:
            payload["doc_size"] = msg.media.document.size
            payload["doc_id"] = msg.media.document.id
        elif isinstance(msg.media, MessageMediaPhoto) and msg.media.photo:
            payload["photo_id"] = msg.media.photo.id
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def is_duplicate_message(self, dedupe_state, msg):
        if not dedupe_state:
            return False
        message_ids = set(dedupe_state.get("message_ids", []))
        fingerprints = set(dedupe_state.get("fingerprints", []))
        return msg.id in message_ids or self.get_message_fingerprint(msg) in fingerprints

    def mark_message_deduped(self, dedupe_state, msg):
        if dedupe_state is None:
            return
        message_ids = dedupe_state.setdefault("message_ids", [])
        fingerprints = dedupe_state.setdefault("fingerprints", [])
        message_ids.append(msg.id)
        fingerprints.append(self.get_message_fingerprint(msg))

    def rpc_get_dashboard(self):
        history_items = self._read_history_entries(limit=25)
        successful_runs = [item for item in history_items if item.get("status") == "success"]
        total_processed = sum(int(item.get("cloned", 0) or 0) for item in history_items)
        total_media = sum(int(item.get("media_files", 0) or 0) for item in history_items)
        total_ram_bypass = sum(int(item.get("ram_bypass_used", item.get("downloaded", 0)) or 0) for item in history_items)
        total_copy_message = sum(int(item.get("copy_message_used", 0) or 0) for item in history_items)
        total_errors = sum(int(item.get("errors", 0) or 0) for item in history_items)
        total_duplicates = sum(int(item.get("skipped_duplicates", 0) or 0) for item in history_items)
        avg_rate = 0
        if successful_runs:
            rates = [float(item.get("messages_per_minute", 0) or 0) for item in successful_runs if item.get("messages_per_minute")]
            avg_rate = round(sum(rates) / len(rates), 2) if rates else 0

        return {
            "active_job": self.runtime_state.get("active_job"),
            "last_job": self.runtime_state.get("last_job"),
            "sync_state": self.sync_state,
            "recent_history": history_items[:10],
            "error_summary": self.rpc_get_error_summary().get("items", [])[:8],
            "summary": {
                "runs": len(history_items),
                "success_rate": round((len(successful_runs) / len(history_items)) * 100, 2) if history_items else 0,
                "total_processed": total_processed,
                "total_media": total_media,
                "total_ram_bypass": total_ram_bypass,
                "total_copy_message": total_copy_message,
                "total_errors": total_errors,
                "total_duplicates": total_duplicates,
                "avg_rate": avg_rate,
            },
        }

    async def rpc_dry_run(self, source="", dest="", limit=0, mode="clone"):
        if not self.logged_in:
            raise Exception("Não conectado")

        self._dialogs_cached = False
        source_entity, source_topic_id = await self.resolve_target(source)
        dest_entity, dest_topic_id = await self.resolve_target(dest)

        source_title = getattr(source_entity, "title", str(source))
        dest_title = getattr(dest_entity, "title", str(dest))
        total_messages = 0
        media_messages = 0
        estimated_bytes = 0

        async for msg in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(limit=limit, reply_to=source_topic_id)
        ):
            total_messages += 1
            if msg.media:
                media_messages += 1
            if isinstance(msg.media, MessageMediaDocument) and msg.media.document:
                estimated_bytes += msg.media.document.size or 0

        saved_progress = None
        progress_file = self.get_progress_filename(source, dest)
        if progress_file.exists():
            saved_progress = self._load_json_file(progress_file, None)

        dedupe_state = self.load_dedupe_state(source, dest)
        warnings = []
        if total_messages == 0:
            warnings.append("Nenhuma mensagem encontrada para o escopo informado.")
        if source_topic_id and not dest_topic_id and mode == "clone":
            warnings.append("A origem aponta para um tópico específico; confirme se o destino é o tópico esperado.")
        if saved_progress:
            warnings.append("Existe um progresso salvo para este par de chats.")

        return {
            "ok": True,
            "mode": mode,
            "source_title": source_title,
            "dest_title": dest_title,
            "total_messages": total_messages,
            "media_messages": media_messages,
            "estimated_bytes": estimated_bytes,
            "estimated_size": self._format_bytes(estimated_bytes),
            "resumable": bool(saved_progress),
            "saved_progress": saved_progress,
            "known_duplicates": len(dedupe_state.get("fingerprints", [])),
            "warnings": warnings,
        }

    # ── Connection ──

    async def _dispose_client(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.logged_in = False

    def _get_local_session_paths(self):
        base = Path(f"{self.session_base_path}.session")
        return [
            base,
            Path(f"{base}-journal"),
            Path(f"{base}-wal"),
            Path(f"{base}-shm"),
        ]

    def _has_local_session_file(self):
        return any(path.exists() for path in self._get_local_session_paths())

    def _clear_local_session_files(self):
        removed = False
        for path in self._get_local_session_paths():
            try:
                if path.exists():
                    path.unlink()
                    removed = True
            except Exception as exc:
                self.log(f"Não foi possível remover {path.name}: {exc}", "warning")
        return removed

    def _export_session_string(self):
        if not self.client or not getattr(self.client, "session", None):
            return ""
        try:
            return StringSession.save(self.client.session) or ""
        except Exception as exc:
            self.log(f"Falha ao exportar a session_string: {exc}", "warning")
            return ""

    def _build_user_payload(self, me):
        return {
            "name": me.first_name or "",
            "username": me.username,
        }

    async def _complete_login(self, log_prefix):
        self.logged_in = True
        me = await self.client.get_me()
        user = self._build_user_payload(me)
        username = f"(@{user['username']})" if user.get("username") else ""
        identity = f"{user['name']} {username}".strip()
        self.log(f"{log_prefix}: {identity}", "success")
        self.emit_status("connected")
        return {
            "ok": True,
            "user": user,
            "session_string": self._export_session_string(),
        }

    def _normalize_session_string(self, session_string=""):
        return (session_string or "").strip()

    def _has_saved_session_candidates(self, session_string=""):
        return bool(self._normalize_session_string(session_string) or self._has_local_session_file())

    def _build_saved_session_candidates(self, session_string=""):
        normalized_session = self._normalize_session_string(session_string)
        candidates = []

        if normalized_session:
            candidates.append({
                "kind": "string",
                "session_string": normalized_session,
                "prefer_disk_session": False,
            })

        if self._has_local_session_file():
            candidates.append({
                "kind": "disk",
                "session_string": "",
                "prefer_disk_session": True,
            })

        return candidates

    async def _try_saved_session_login(self, api_id, api_hash, session_string=""):
        invalid_sources = []
        last_error = None

        for candidate in self._build_saved_session_candidates(session_string):
            kind = candidate["kind"]
            try:
                await self._create_client(
                    api_id,
                    api_hash,
                    session_string=candidate["session_string"],
                    prefer_disk_session=candidate["prefer_disk_session"],
                )
                if await self.client.is_user_authorized():
                    return {
                        "ok": True,
                        "source": kind,
                        "invalid_sources": invalid_sources,
                        "last_error": last_error,
                    }
                self.log(f"Sessão armazenada ({kind}) não está mais autorizada.", "warning")
            except Exception as exc:
                last_error = exc
                self.log(f"Falha ao abrir a sessão armazenada ({kind}): {exc}", "warning")

            invalid_sources.append(kind)
            await self._dispose_client()

        return {
            "ok": False,
            "invalid_sources": invalid_sources,
            "last_error": last_error,
        }

    def _clear_invalid_session_sources(self, invalid_sources):
        normalized = set(invalid_sources or [])
        cleared_local_session = False

        if "disk" in normalized:
            cleared_local_session = self._clear_local_session_files()

        return {
            "reset_session": "string" in normalized,
            "cleared_local_session": cleared_local_session,
            "cleared_sources": sorted(normalized),
        }

    async def _recover_clean_session_client(self, api_id, api_hash, reason):
        self.log(reason, "warning")
        return False

    async def _create_client(self, api_id, api_hash, session_string="", prefer_disk_session=False):
        await self._dispose_client()
        session_string = self._normalize_session_string(session_string)

        if session_string:
            session = StringSession(session_string)
        elif prefer_disk_session and self._has_local_session_file():
            session = str(self.session_base_path)
        else:
            session = StringSession()

        self.client = TelegramClient(
            session,
            api_id,
            api_hash,
            timeout=self.connect_timeout,
            connection_retries=2,
            retry_delay=1,
            flood_sleep_threshold=120,
            use_ipv6=False
        )
        try:
            await asyncio.wait_for(self.client.connect(), timeout=self.connect_timeout)
        except asyncio.TimeoutError as exc:
            self.log("Timeout ao conectar no Telegram. Verifique sua rede ou as credenciais da API.", "error")
            self.emit_status("disconnected")
            await self._dispose_client()
            raise RuntimeError("Timeout ao conectar no Telegram") from exc
        except Exception:
            self.emit_status("disconnected")
            await self._dispose_client()
            raise

    async def rpc_connect(self, api_id="", api_hash="", phone="", password="", session_string=""):
        self.emit_status("connecting")
        api_id = int(api_id)
        session_string = self._normalize_session_string(session_string)
        session_reset = False

        if self._has_saved_session_candidates(session_string):
            saved_login = await self._try_saved_session_login(api_id, api_hash, session_string=session_string)
            if saved_login.get("ok"):
                result = await self._complete_login("Conectado como")
                result["needs_code"] = False
                result["reset_session"] = False
                result["cleared_local_session"] = False
                return result

            cleanup = self._clear_invalid_session_sources(saved_login.get("invalid_sources"))
            session_reset = cleanup["reset_session"]
            cleared_local_session = cleanup["cleared_local_session"]

            await self._create_client(api_id, api_hash, session_string="", prefer_disk_session=False)

            if not await self.client.is_user_authorized():
                self.log("Enviando código de verificação...", "info")
                await self.client.send_code_request(phone)
                self.emit_status("awaiting_code")
                return {
                    "ok": True,
                    "needs_code": True,
                    "reset_session": session_reset,
                    "cleared_local_session": cleared_local_session,
                }

            result = await self._complete_login("Conectado como")
            result["needs_code"] = False
            result["reset_session"] = session_reset
            result["cleared_local_session"] = cleared_local_session
            return result

        try:
            await self._create_client(
                api_id,
                api_hash,
                session_string=session_string,
                prefer_disk_session=not bool(session_string),
            )
        except Exception:
            if (session_string or self._has_local_session_file()) and await self._recover_clean_session_client(
                api_id,
                api_hash,
                "Sessão armazenada falhou. Recriando uma sessão limpa sem exigir deleção manual...",
            ):
                session_reset = True
            else:
                raise

        if not await self.client.is_user_authorized():
            self.log("Enviando código de verificação...", "info")
            await self.client.send_code_request(phone)
            self.emit_status("awaiting_code")
            return {"ok": True, "needs_code": True, "reset_session": session_reset}

        result = await self._complete_login("Conectado como")
        result["needs_code"] = False
        result["reset_session"] = session_reset
        return result

    async def rpc_submit_code(self, phone="", code="", password=""):
        try:
            await self.client.sign_in(phone, code)
        except SessionPasswordNeededError:
            if not password:
                self.emit_status("awaiting_2fa")
                return {"ok": True, "needs_2fa": True}
            await self.client.sign_in(password=password)

        return await self._complete_login("Conectado como")

    async def rpc_submit_2fa(self, password=""):
        await self.client.sign_in(password=password)
        return await self._complete_login("Conectado como")

    async def rpc_auto_login(self, api_id="", api_hash="", session_string=""):
        session_string = self._normalize_session_string(session_string)
        if self._has_saved_session_candidates(session_string):
            api_id = int(api_id)
            self.emit_status("connecting")

            saved_login = await self._try_saved_session_login(api_id, api_hash, session_string=session_string)
            if saved_login.get("ok"):
                result = await self._complete_login("Login automático")
                result["reset_session"] = False
                result["cleared_local_session"] = False
                return result

            cleanup = self._clear_invalid_session_sources(saved_login.get("invalid_sources"))
            await self._dispose_client()
            self.emit_status("disconnected")
            if cleanup["reset_session"] or cleanup["cleared_local_session"]:
                self.log("A sessão salva ficou inválida. Limpe a sessão local e faça um novo login.", "warning")

            return {
                "ok": False,
                "error": "Session expired" if saved_login.get("invalid_sources") else str(saved_login.get("last_error") or "Session expired"),
                "needs_reauth": bool(saved_login.get("invalid_sources")),
                "reset_session": cleanup["reset_session"],
                "cleared_local_session": cleanup["cleared_local_session"],
            }

        has_disk_session = self._has_local_session_file()
        if not session_string and not has_disk_session:
            self.emit_status("disconnected")
            return {"ok": False, "error": "No stored session", "needs_reauth": False, "reset_session": False}

        api_id = int(api_id)
        self.emit_status("connecting")

        try:
            await self._create_client(
                api_id,
                api_hash,
                session_string=session_string,
                prefer_disk_session=not bool(session_string),
            )
        except Exception as exc:
            recovered = False
            if session_string or has_disk_session:
                recovered = await self._recover_clean_session_client(
                    api_id,
                    api_hash,
                    "Sessão automática inválida ou travada. Limpando a sessão local e preparando um novo handshake...",
                )
            await self._dispose_client()
            self.emit_status("disconnected")
            if recovered:
                return {"ok": False, "error": "Stored session reset", "needs_reauth": True, "reset_session": True}
            return {"ok": False, "error": str(exc), "needs_reauth": False, "reset_session": False}

        if await self.client.is_user_authorized():
            return await self._complete_login("Login automático")

        await self._dispose_client()
        self._clear_local_session_files()
        self.emit_status("disconnected")
        return {"ok": False, "error": "Session expired", "needs_reauth": True, "reset_session": True}

    # ── Entity Resolution ──

    async def rpc_clear_session(self):
        if self.runtime_state.get("active_job") or self.sync_state.get("active"):
            raise Exception("Pare as operações ativas antes de limpar a sessão.")

        await self._dispose_client()
        cleared_local_session = self._clear_local_session_files()
        self._dialogs_cached = False
        self.emit_status("disconnected")
        self.log("Sessão local removida. Inicie um novo handshake para entrar novamente.", "warning")
        return {
            "ok": True,
            "reset_session": True,
            "cleared_local_session": cleared_local_session,
        }

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

    async def _get_forum_input_channel(self, entity, label="grupo"):
        resolved = entity
        try:
            resolved = await self.client.get_entity(entity)
        except Exception:
            pass

        if isinstance(resolved, ChannelForbidden):
            raise ValueError(
                f"A conta conectada não consegue acessar o {label}. Entre no grupo com esta conta e tente novamente."
            )

        if not isinstance(resolved, Channel):
            raise ValueError(
                f"O {label} precisa ser um supergrupo do Telegram. Grupos básicos não suportam tópicos."
            )

        if not getattr(resolved, "megagroup", False):
            raise ValueError(
                f"O {label} precisa ser um supergrupo do Telegram para usar tópicos."
            )

        if not getattr(resolved, "forum", False):
            raise ValueError(
                f"O {label} precisa ter o modo fórum/tópicos ativado antes da clonagem."
            )

        try:
            input_channel = get_input_channel(resolved)
        except TypeError as exc:
            raise ValueError(
                f"Não foi possível resolver o canal do {label}. Abra o grupo pelo menos uma vez com esta conta e tente novamente."
            ) from exc

        if not isinstance(input_channel, InputChannel):
            raise ValueError(
                f"O {label} não foi resolvido como um canal válido para criação de tópicos."
            )

        return input_channel

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

    def _is_media_file(self, message):
        media = getattr(message, "media", None)
        if not media:
            return False
        return not isinstance(
            media,
            (
                MessageMediaWebPage,
                MessageMediaContact,
                MessageMediaGeo,
                MessageMediaGeoLive,
                MessageMediaVenue,
                MessageMediaPoll,
                MessageMediaGame,
                MessageMediaInvoice,
                MessageMediaDice,
                MessageMediaUnsupported,
            ),
        )

    def _is_restricted_forward_error(self, exc):
        error_text = f"{type(exc).__name__} {exc}".lower()
        restricted_tokens = (
            "protected",
            "forwards restricted",
            "message_protected",
            "chatforwardsrestricted",
            "chat_forwards_restricted",
            "cannot be forwarded",
        )
        return any(token in error_text for token in restricted_tokens)

    def _is_message_id_invalid_error(self, exc):
        lowered = f"{type(exc).__name__} {exc}".lower()
        return "messageidinvalid" in lowered or "message_id_invalid" in lowered

    def _should_fallback_after_copy_failure(self, exc):
        if isinstance(exc, FloodWaitError):
            return False
        if isinstance(exc, (AttributeError, NotImplementedError, TypeError)):
            return True

        lowered = f"{type(exc).__name__} {exc}".lower()
        blocking_tokens = (
            "timeout",
            "timed out",
            "network",
            "connection",
            "session",
            "authorized",
            "authorization",
            "password",
            "forbidden",
            "permission",
            "write forbidden",
            "admin",
            "banned",
            "slowmode",
            "slow mode",
        )
        if any(token in lowered for token in blocking_tokens):
            return False

        compatible_tokens = (
            "copy",
            "forward",
            "drop_author",
            "drop_media_captions",
            "messageidinvalid",
            "message_id_invalid",
            "media empty",
            "media_empty",
            "media invalid",
            "grouped_media_invalid",
            "reply_to",
            "topic",
            "top_msg_id",
            "unsupported",
            "poll",
            "contact",
            "geo",
            "venue",
            "dice",
            "game",
            "invoice",
        )
        return (
            self._is_restricted_forward_error(exc)
            or isinstance(exc, RPCError)
            or any(token in lowered for token in compatible_tokens)
        )

    def _extract_media_attributes(self, msg):
        attributes = getattr(msg.media, "attributes", None)
        document = getattr(msg.media, "document", None)
        if document:
            attributes = getattr(document, "attributes", None) or attributes
        return list(attributes) if attributes else None

    def _guess_media_filename(self, msg):
        if isinstance(msg.media, MessageMediaPhoto):
            return f"photo_{msg.id}.jpg"

        message_file = getattr(msg, "file", None)
        file_name = getattr(message_file, "name", None)
        if file_name:
            return file_name

        document = getattr(msg.media, "document", None)
        if document:
            for attr in document.attributes or []:
                if isinstance(attr, DocumentAttributeFilename) and attr.file_name:
                    return attr.file_name

        ext = getattr(message_file, "ext", None)
        if not ext:
            mime_type = getattr(document, "mime_type", None)
            mime_extensions = {
                "application/x-tgsticker": ".tgs",
                "audio/ogg": ".ogg",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
                "video/mp4": ".mp4",
                "video/webm": ".webm",
            }
            ext = mime_extensions.get(mime_type) or mimetypes.guess_extension(mime_type or "") or ".bin"
        if not str(ext).startswith("."):
            ext = f".{ext}"
        return f"media_{msg.id}{ext}"

    async def _run_with_floodwait_retry(self, coro_func, *args, action="operação", **kwargs):
        while True:
            try:
                return await coro_func(*args, **kwargs)
            except FloodWaitError as exc:
                wait_seconds = max(int(getattr(exc, "seconds", 0) or 0), 1) + 2
                self._log_scope("retry", f"FloodWait em {action}; retry em {wait_seconds}s.", "warning")
                await asyncio.sleep(wait_seconds)

    async def _send_media_via_ram_bypass(self, dest_entity, msg, reply_to=None):
        if not msg.media:
            return False

        self._last_send_used_copy_message = False
        self._last_send_used_ram_bypass = True
        self._log_scope("ram", f"Mensagem #{msg.id} protegida; reenviando via RAM.", "warning")
        attributes = self._extract_media_attributes(msg)
        download_action = f"download em RAM da msg #{msg.id}"
        upload_action = f"reupload em RAM da msg #{msg.id}"
        bytes_data = await self._run_with_floodwait_retry(
            self.client.download_media,
            msg,
            file=bytes,
            action=download_action,
        )
        if not bytes_data:
            raise Exception(f"Falha ao baixar a mídia protegida da msg #{msg.id} em memória")

        # Reenvia a mídia a partir da RAM para evitar I/O em disco e preservar os metadados originais.
        upload_buffer = io.BytesIO(bytes_data)
        upload_buffer.name = self._guess_media_filename(msg)
        kwargs = {
            "caption": msg.message or "",
            "formatting_entities": msg.entities,
            "parse_mode": None,
            "attributes": attributes,
            "force_document": isinstance(msg.media, MessageMediaDocument) and not self._is_visual_media(msg.media),
        }
        if reply_to:
            kwargs["reply_to"] = reply_to
        if attributes:
            kwargs["voice_note"] = any(isinstance(attr, DocumentAttributeAudio) and attr.voice for attr in attributes)
            kwargs["video_note"] = any(isinstance(attr, DocumentAttributeVideo) and attr.round_message for attr in attributes)
            kwargs["supports_streaming"] = any(
                isinstance(attr, DocumentAttributeVideo) and not attr.round_message
                for attr in attributes
            )

        await self._run_with_floodwait_retry(
            self.client.send_file,
            dest_entity,
            upload_buffer,
            action=upload_action,
            **kwargs,
        )
        return True

    async def _copy_message_first(self, source_entity, dest_entity, msg, reply_to=None):
        copy_method = getattr(self.client, "copy_message", None)
        if callable(copy_method):
            kwargs = {
                "chat_id": dest_entity,
                "from_chat_id": source_entity,
                "message_id": msg.id,
            }
            if reply_to:
                kwargs["reply_to_message_id"] = reply_to
            await copy_method(**kwargs)
            return True

        request = functions.messages.ForwardMessagesRequest(
            from_peer=await self.client.get_input_entity(source_entity),
            id=[msg.id],
            random_id=[random.randint(1, 2**63 - 1)],
            to_peer=await self.client.get_input_entity(dest_entity),
            drop_author=True,
            top_msg_id=reply_to or None,
        )
        await self.client(request)
        return True

    async def _send_message_via_legacy_fallback(self, dest_entity, msg, reply_to=None):
        self._last_send_used_copy_message = False
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

            if getattr(msg, "noforwards", False):
                self._log_scope("ram", f"Mensagem #{msg.id} marcada como protegida; usando bypass RAM.", "warning")
                return await self._send_media_via_ram_bypass(dest_entity, msg, reply_to=reply_to)

            try:
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
            except Exception as exc:
                if self._is_restricted_forward_error(exc):
                    self._log_scope("ram", f"Mensagem #{msg.id} bloqueou envio direto; usando bypass RAM.", "warning")
                    return await self._send_media_via_ram_bypass(dest_entity, msg, reply_to=reply_to)
                raise

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

    async def _send_message_like_main(self, source_entity, dest_entity, msg, reply_to=None):
        self._last_send_used_ram_bypass = False
        self._last_send_used_copy_message = False

        try:
            sent = await self._copy_message_first(source_entity, dest_entity, msg, reply_to=reply_to)
            if sent:
                self._last_send_used_copy_message = True
            return sent
        except Exception as exc:
            if not self._should_fallback_after_copy_failure(exc):
                raise
            if not self._is_message_id_invalid_error(exc):
                self._log_scope(
                    "copy",
                    f"Mensagem #{msg.id} falhou no copy_message ({type(exc).__name__}); usando fallback.",
                    "warning",
                )

        return await self._send_message_via_legacy_fallback(dest_entity, msg, reply_to=reply_to)

    async def _deliver_message_with_refresh(self, source_entity, dest_entity, msg, reply_to=None):
        try:
            sent = await self._send_message_like_main(source_entity, dest_entity, msg, reply_to=reply_to)
            return sent, msg
        except Exception as exc:
            if not is_file_reference_error(exc):
                raise

            refreshed = await self.client.get_messages(source_entity, ids=[msg.id])
            refreshed_msg = refreshed[0] if refreshed and refreshed[0] else None
            if not refreshed_msg:
                raise

            sent = await self._send_message_like_main(source_entity, dest_entity, refreshed_msg, reply_to=reply_to)
            return sent, refreshed_msg

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

    def get_saved_progress_entry(self, source, dest):
        progress_file = self.get_progress_filename(source, dest)
        if not progress_file.exists():
            return None
        return self._load_json_file(progress_file, None)

    def save_progress(self, source, dest, last_msg_id, cloned, total, source_title, dest_title, extra=None):
        pf = self.get_progress_filename(source, dest)
        data = {
            "source": source, "dest": dest,
            "source_title": source_title, "dest_title": dest_title,
            "last_message_id": last_msg_id, "cloned": cloned, "total": total,
            "timestamp": datetime.now().isoformat(),
        }
        if extra:
            data.update(extra)
        pf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete_progress_file(self, source, dest):
        pf = self.get_progress_filename(source, dest)
        if pf.exists():
            pf.unlink()

    # ── Clone Operations ──

    async def rpc_clone(
        self,
        source="",
        dest="",
        limit=0,
        delay=0.1,
        pause_every=50,
        pause_duration=2,
        pause_every_min=None,
        pause_every_max=None,
        pause_duration_min=None,
        pause_duration_max=None,
        resume_from_msg_id=None,
    ):
        if not self.logged_in:
            raise Exception("Não conectado ao Telegram")

        self.stop_flag = False
        self._dialogs_cached = False
        started_at = datetime.now().isoformat()
        config = self.rpc_load_config()
        dedupe_enabled = config.get("dedupe_enabled", True)
        dedupe_state = self.load_dedupe_state(source, dest) if dedupe_enabled else None
        anti_flood = self._resolve_anti_flood_config(
            pause_every=pause_every,
            pause_duration=pause_duration,
            pause_every_min=pause_every_min,
            pause_every_max=pause_every_max,
            pause_duration_min=pause_duration_min,
            pause_duration_max=pause_duration_max,
        )
        skipped_duplicates = 0

        self.emit_progress({"type": "clone", "status": "starting", "copy_message_used": 0})
        self._log_scope("clone", "Preparando operação e resolvendo entidades...", "info")

        source_entity, source_topic_id = await self.resolve_target(source)
        dest_entity, dest_topic_id = await self.resolve_target(dest)

        source_title = getattr(source_entity, "title", str(source))
        dest_title = getattr(dest_entity, "title", str(dest))
        if source_topic_id:
            source_title = f"{source_title} > tópico {source_topic_id}"
        if dest_topic_id:
            dest_title = f"{dest_title} > tópico {dest_topic_id}"
        self._log_scope("clone", f"Origem  | {source_title}", "info")
        self._log_scope("clone", f"Destino | {dest_title}", "info")
        self._set_active_job("clone", {
            "status": "starting",
            "source_title": source_title,
            "dest_title": dest_title,
            "source": source,
            "dest": dest,
            "started_at": started_at,
            "processed": 0,
            "media_files": 0,
            "ram_bypass_used": 0,
            "copy_message_used": 0,
            "total": 0,
            "errors": 0,
            "skipped_duplicates": 0,
        })

        total = 0
        async for _ in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(limit=limit, reply_to=source_topic_id)
        ):
            total += 1
        self._log_scope("clone", f"Mensagens no escopo: {total}", "info")

        if total == 0:
            self._log_scope("clone", "Nenhuma mensagem encontrada no escopo.", "warning")
            self.emit_progress({
                "type": "clone",
                "status": "done",
                "cloned": 0,
                "total": 0,
                "copy_message_used": 0,
            })
            self._finish_active_job({
                "operation": "clone",
                "status": "success",
                "source_title": source_title,
                "dest_title": dest_title,
                "source": source,
                "dest": dest,
                "processed": 0,
                "media_files": 0,
                "ram_bypass_used": 0,
                "copy_message_used": 0,
                "total": 0,
                "errors": 0,
                "skipped_duplicates": 0,
                "messages_per_minute": 0,
            })
            return {"ok": True, "cloned": 0, "copy_message_used": 0}

        resume_entry = self.get_saved_progress_entry(source, dest) if resume_from_msg_id else None
        resume_offset = int((resume_entry or {}).get("cloned", 0) or 0)
        media_files = int((resume_entry or {}).get("media_files", 0) or 0)
        ram_bypass_used = int((resume_entry or {}).get("ram_bypass_used", 0) or 0)
        copy_message_used = int((resume_entry or {}).get("copy_message_used", 0) or 0)

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
        completed = resume_offset
        last_completed_msg_id = int(resume_from_msg_id or 0)
        total_scope = total
        loop_started_at = time.time()
        anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)

        for msg in messages:
            if self.stop_flag:
                self._log_scope("clone", "Operação interrompida pelo usuário.", "warning")
                self.save_progress(
                    source,
                    dest,
                    last_completed_msg_id,
                    completed,
                    total_scope,
                    source_title,
                    dest_title,
                    {
                        "media_files": media_files,
                        "ram_bypass_used": ram_bypass_used,
                        "copy_message_used": copy_message_used,
                    },
                )
                break

            try:
                media_type = self.get_media_type(msg)

                if dedupe_enabled and self.is_duplicate_message(dedupe_state, msg):
                    skipped_duplicates += 1
                    completed += 1
                    last_completed_msg_id = msg.id
                    metrics = self._build_runtime_metrics(loop_started_at, completed, total_scope)
                    self.emit_progress({
                        "type": "clone",
                        "status": "running",
                        "cloned": completed,
                        "total": total_scope,
                        "percent": int((completed / total_scope) * 100) if total_scope else 0,
                        "media_type": media_type,
                        "media_files": media_files,
                        "ram_bypass_used": ram_bypass_used,
                        "copy_message_used": copy_message_used,
                        "skipped_duplicates": skipped_duplicates,
                        **metrics,
                    })
                    self._set_active_job("clone", {
                        "status": "running",
                        "source_title": source_title,
                        "dest_title": dest_title,
                        "source": source,
                        "dest": dest,
                        "started_at": started_at,
                        "processed": completed,
                        "media_files": media_files,
                        "ram_bypass_used": ram_bypass_used,
                        "copy_message_used": copy_message_used,
                        "total": total_scope,
                        "errors": errors,
                        "skipped_duplicates": skipped_duplicates,
                        **metrics,
                    })
                    continue

                sent, delivered_msg = await self._deliver_message_with_refresh(
                    source_entity,
                    dest_entity,
                    msg,
                    reply_to=dest_topic_id,
                )
                if not sent:
                    cloned += 1
                    completed += 1
                    last_completed_msg_id = msg.id
                    if dedupe_enabled:
                        self.mark_message_deduped(dedupe_state, msg)
                    continue

                cloned += 1
                completed += 1
                last_completed_msg_id = msg.id
                if self._is_media_file(delivered_msg):
                    media_files += 1
                if self._last_send_used_ram_bypass:
                    ram_bypass_used += 1
                if self._last_send_used_copy_message:
                    copy_message_used += 1
                if dedupe_enabled:
                    self.mark_message_deduped(dedupe_state, msg)
                pct = int((completed / total_scope) * 100) if total_scope else 0
                metrics = self._build_runtime_metrics(loop_started_at, completed, total_scope)
                self.emit_progress({
                    "type": "clone",
                    "status": "running",
                    "cloned": completed,
                    "total": total_scope,
                    "percent": pct,
                    "media_type": media_type,
                    "media_files": media_files,
                    "ram_bypass_used": ram_bypass_used,
                    "copy_message_used": copy_message_used,
                    "skipped_duplicates": skipped_duplicates,
                    **metrics,
                })
                self._set_active_job("clone", {
                    "status": "running",
                    "source_title": source_title,
                    "dest_title": dest_title,
                    "source": source,
                    "dest": dest,
                    "started_at": started_at,
                    "processed": completed,
                    "media_files": media_files,
                    "ram_bypass_used": ram_bypass_used,
                    "copy_message_used": copy_message_used,
                    "total": total_scope,
                    "errors": errors,
                    "skipped_duplicates": skipped_duplicates,
                    **metrics,
                })

                if completed % 10 == 0:
                    self._log_scope("clone", f"Progresso | {completed}/{total_scope} ({pct}%)", "info")
                    self.save_progress(
                        source,
                        dest,
                        last_completed_msg_id,
                        completed,
                        total_scope,
                        source_title,
                        dest_title,
                        {
                            "media_files": media_files,
                            "ram_bypass_used": ram_bypass_used,
                            "copy_message_used": copy_message_used,
                        },
                    )
                    if dedupe_enabled:
                        dedupe_state = self.save_dedupe_state(source, dest, dedupe_state)

                if anti_flood_cycle and cloned >= anti_flood_cycle["after_messages"]:
                    pause_seconds = anti_flood_cycle["duration"]
                    self._log_scope(
                        "clone",
                        f"Pausa anti-flood | {self._format_seconds(pause_seconds)}s após {anti_flood_cycle['frequency']} envios.",
                        "warning",
                    )
                    await asyncio.sleep(pause_seconds)
                    anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)

                await asyncio.sleep(delay)

            except FloodWaitError as e:
                wait = e.seconds + 5
                self._log_scope("clone", f"FloodWait detectado; aguardando {wait}s para retomar.", "error")
                self._record_error(e, "clone", {"source": source_title, "dest": dest_title, "message_id": msg.id})
                self.save_progress(
                    source,
                    dest,
                    last_completed_msg_id,
                    completed,
                    total_scope,
                    source_title,
                    dest_title,
                    {
                        "media_files": media_files,
                        "ram_bypass_used": ram_bypass_used,
                        "copy_message_used": copy_message_used,
                    },
                )
                await asyncio.sleep(wait)
                anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)
            except Exception as e:
                errors += 1
                self._record_error(e, "clone", {"source": source_title, "dest": dest_title, "message_id": msg.id})
                self._log_scope("clone", f"Erro na mensagem #{msg.id}: {e}", "error")

        if dedupe_enabled:
            dedupe_state = self.save_dedupe_state(source, dest, dedupe_state)

        metrics = self._build_runtime_metrics(loop_started_at, completed, total_scope)
        status = "stopped" if self.stop_flag else "success"
        if not self.stop_flag:
            self.delete_progress_file(source, dest)
        self._log_scope(
            "clone",
            f"Concluído | mensagens: {completed}/{total_scope} | erros: {errors} | duplicadas: {skipped_duplicates}",
            "success" if not self.stop_flag else "warning",
        )
        self._log_route_summary("clone", copy_message_used=copy_message_used, ram_bypass_used=ram_bypass_used, tag="info")
        self.emit_progress({
            "type": "clone",
            "status": "done" if not self.stop_flag else "stopped",
            "cloned": completed,
            "total": total_scope,
            "media_files": media_files,
            "ram_bypass_used": ram_bypass_used,
            "copy_message_used": copy_message_used,
            "errors": errors,
            "skipped_duplicates": skipped_duplicates,
            **metrics,
        })
        self._append_history_entry(self._create_history_entry(
            "clone",
            status,
            source,
            dest,
            source_title,
            dest_title,
            started_at,
            cloned=completed,
            total=total_scope,
            media_files=media_files,
            ram_bypass_used=ram_bypass_used,
            copy_message_used=copy_message_used,
            errors=errors,
            skipped_duplicates=skipped_duplicates,
            messages_per_minute=metrics["messages_per_minute"],
        ))
        self._finish_active_job({
            "operation": "clone",
            "status": status,
            "source_title": source_title,
            "dest_title": dest_title,
            "source": source,
            "dest": dest,
            "processed": completed,
            "media_files": media_files,
            "ram_bypass_used": ram_bypass_used,
            "copy_message_used": copy_message_used,
            "total": total_scope,
            "errors": errors,
            "skipped_duplicates": skipped_duplicates,
            **metrics,
        })
        return {
            "ok": True,
            "cloned": completed,
            "total": total_scope,
            "media_files": media_files,
            "ram_bypass_used": ram_bypass_used,
            "copy_message_used": copy_message_used,
            "errors": errors,
            "skipped_duplicates": skipped_duplicates,
            "status": status,
        }

    async def rpc_stop(self):
        self.stop_flag = True
        self._log_scope("clone", "Solicitação de parada recebida.", "warning")
        return {"ok": True}

    async def _live_sync_loop(self, source, dest, source_entity, dest_entity, source_title, dest_title,
                              source_topic_id, dest_topic_id, poll_interval, delay, dedupe_state, anti_flood):
        anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, self.sync_state.get("processed", 0))
        while self.sync_state.get("active"):
            try:
                messages = []
                async for msg in self.client.iter_messages(
                    source_entity,
                    **self.get_iter_messages_kwargs(
                        limit=0,
                        reverse=True,
                        reply_to=source_topic_id,
                        min_id=self.sync_state.get("last_seen_id") or None,
                    )
                ):
                    messages.append(msg)

                for msg in messages:
                    if not self.sync_state.get("active"):
                        break
                    try:
                        if dedupe_state and self.is_duplicate_message(dedupe_state, msg):
                            self.sync_state["skipped_duplicates"] += 1
                            self.sync_state["last_seen_id"] = max(self.sync_state.get("last_seen_id", 0), msg.id)
                            continue

                        sent, delivered_msg = await self._deliver_message_with_refresh(
                            source_entity,
                            dest_entity,
                            msg,
                            reply_to=dest_topic_id,
                        )
                        self.sync_state["last_seen_id"] = max(self.sync_state.get("last_seen_id", 0), msg.id)
                        if sent:
                            self.sync_state["processed"] += 1
                            if self._is_media_file(delivered_msg):
                                self.sync_state["media_files"] += 1
                            if self._last_send_used_ram_bypass:
                                self.sync_state["ram_bypass_used"] += 1
                            if self._last_send_used_copy_message:
                                self.sync_state["copy_message_used"] += 1
                            if dedupe_state is not None:
                                self.mark_message_deduped(dedupe_state, msg)
                            if anti_flood_cycle and self.sync_state["processed"] >= anti_flood_cycle["after_messages"]:
                                pause_seconds = anti_flood_cycle["duration"]
                                self._log_scope(
                                    "sync",
                                    f"Pausa anti-flood | {self._format_seconds(pause_seconds)}s após {anti_flood_cycle['frequency']} envios.",
                                    "warning",
                                )
                                await asyncio.sleep(pause_seconds)
                                anti_flood_cycle = self._next_anti_flood_cycle(
                                    anti_flood,
                                    self.sync_state["processed"],
                                )
                        metrics = self._build_runtime_metrics(
                            datetime.fromisoformat(self.sync_state["started_at"]).timestamp(),
                            self.sync_state["processed"] + self.sync_state["skipped_duplicates"],
                            max(self.sync_state["processed"] + self.sync_state["skipped_duplicates"], 1),
                        )
                        self.emit_progress({
                            "type": "sync",
                            "status": "running",
                            "processed": self.sync_state["processed"],
                            "media_files": self.sync_state["media_files"],
                            "ram_bypass_used": self.sync_state["ram_bypass_used"],
                            "copy_message_used": self.sync_state["copy_message_used"],
                            "skipped_duplicates": self.sync_state["skipped_duplicates"],
                            "errors": self.sync_state["errors"],
                            "poll_interval": poll_interval,
                            "source_title": source_title,
                            "dest_title": dest_title,
                            "last_seen_id": self.sync_state["last_seen_id"],
                            **metrics,
                        })
                        await asyncio.sleep(delay)
                    except FloodWaitError as e:
                        self.sync_state["errors"] += 1
                        self._record_error(e, "sync", {"source": source_title, "dest": dest_title, "message_id": msg.id})
                        await asyncio.sleep(e.seconds + 5)
                        anti_flood_cycle = self._next_anti_flood_cycle(
                            anti_flood,
                            self.sync_state.get("processed", 0),
                        )
                    except Exception as exc:
                        self.sync_state["errors"] += 1
                        self._record_error(exc, "sync", {"source": source_title, "dest": dest_title, "message_id": msg.id})
                        self._log_scope("sync", f"Erro na mensagem #{msg.id}: {exc}", "error")

                if dedupe_state is not None:
                    self.save_dedupe_state(source, dest, dedupe_state)
                self.sync_state["last_poll_at"] = datetime.now().isoformat()
                self.emit_progress({
                    "type": "sync",
                    "status": "idle",
                    "processed": self.sync_state["processed"],
                    "media_files": self.sync_state["media_files"],
                    "ram_bypass_used": self.sync_state["ram_bypass_used"],
                    "copy_message_used": self.sync_state["copy_message_used"],
                    "skipped_duplicates": self.sync_state["skipped_duplicates"],
                    "errors": self.sync_state["errors"],
                    "poll_interval": poll_interval,
                    "source_title": source_title,
                    "dest_title": dest_title,
                    "last_seen_id": self.sync_state["last_seen_id"],
                    "last_poll_at": self.sync_state["last_poll_at"],
                })
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.sync_state["errors"] += 1
                self._record_error(exc, "sync", {"source": source_title, "dest": dest_title})
                self._log_scope("sync", f"Loop de sincronização falhou: {exc}", "error")
                await asyncio.sleep(min(max(poll_interval, 5), 15))

    async def rpc_start_live_sync(
        self,
        source="",
        dest="",
        poll_interval=15,
        delay=0.2,
        pause_every=50,
        pause_duration=2,
        pause_every_min=None,
        pause_every_max=None,
        pause_duration_min=None,
        pause_duration_max=None,
    ):
        if not self.logged_in:
            raise Exception("Não conectado")
        if self.sync_task and not self.sync_task.done():
            return {"ok": False, "error": "Sync contínua já está ativa"}

        self._dialogs_cached = False
        config = self.rpc_load_config()
        dedupe_enabled = config.get("dedupe_enabled", True)
        anti_flood = self._resolve_anti_flood_config(
            pause_every=pause_every,
            pause_duration=pause_duration,
            pause_every_min=pause_every_min,
            pause_every_max=pause_every_max,
            pause_duration_min=pause_duration_min,
            pause_duration_max=pause_duration_max,
        )
        dedupe_state = self.load_dedupe_state(source, dest) if dedupe_enabled else None

        source_entity, source_topic_id = await self.resolve_target(source)
        dest_entity, dest_topic_id = await self.resolve_target(dest)
        source_title = getattr(source_entity, "title", str(source))
        dest_title = getattr(dest_entity, "title", str(dest))

        latest_messages = []
        async for msg in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(limit=1, reply_to=source_topic_id)
        ):
            latest_messages.append(msg)
        last_seen_id = latest_messages[0].id if latest_messages else 0

        self.sync_state = {
            "active": True,
            "source": source,
            "dest": dest,
            "source_title": source_title,
            "dest_title": dest_title,
            "processed": 0,
            "media_files": 0,
            "ram_bypass_used": 0,
            "copy_message_used": 0,
            "skipped_duplicates": 0,
            "errors": 0,
            "poll_interval": int(poll_interval or 15),
            "delay": float(delay or 0.2),
            "last_seen_id": last_seen_id,
            "started_at": datetime.now().isoformat(),
            "last_poll_at": None,
        }
        self.sync_task = asyncio.create_task(self._live_sync_loop(
            source,
            dest,
            source_entity,
            dest_entity,
            source_title,
            dest_title,
            source_topic_id,
            dest_topic_id,
            int(poll_interval or 15),
            float(delay or 0.2),
            dedupe_state,
            anti_flood,
        ))
        self._log_scope("sync", f"Iniciada | {source_title} -> {dest_title}", "success")
        self.emit_progress({
            "type": "sync",
            "status": "active",
            "processed": 0,
            "media_files": 0,
            "ram_bypass_used": 0,
            "copy_message_used": 0,
            "skipped_duplicates": 0,
            "errors": 0,
            "poll_interval": int(poll_interval or 15),
            "source_title": source_title,
            "dest_title": dest_title,
            "last_seen_id": last_seen_id,
        })
        return {"ok": True, "sync_state": self.sync_state}

    async def rpc_stop_live_sync(self):
        if not self.sync_task:
            self.sync_state["active"] = False
            return {"ok": True, "sync_state": self.sync_state}

        self.sync_state["active"] = False
        self.sync_task.cancel()
        try:
            await self.sync_task
        except asyncio.CancelledError:
            pass
        finally:
            self.sync_task = None

        source = self.sync_state.get("source", "")
        dest = self.sync_state.get("dest", "")
        source_title = self.sync_state.get("source_title", source)
        dest_title = self.sync_state.get("dest_title", dest)
        self._append_history_entry(self._create_history_entry(
            "sync",
            "stopped",
            source,
            dest,
            source_title,
            dest_title,
            self.sync_state.get("started_at"),
            cloned=self.sync_state.get("processed", 0),
            total=self.sync_state.get("processed", 0),
            media_files=self.sync_state.get("media_files", 0),
            ram_bypass_used=self.sync_state.get("ram_bypass_used", 0),
            copy_message_used=self.sync_state.get("copy_message_used", 0),
            errors=self.sync_state.get("errors", 0),
            skipped_duplicates=self.sync_state.get("skipped_duplicates", 0),
        ))
        self.emit_progress({
            "type": "sync",
            "status": "stopped",
            "processed": self.sync_state.get("processed", 0),
            "media_files": self.sync_state.get("media_files", 0),
            "ram_bypass_used": self.sync_state.get("ram_bypass_used", 0),
            "copy_message_used": self.sync_state.get("copy_message_used", 0),
            "skipped_duplicates": self.sync_state.get("skipped_duplicates", 0),
            "errors": self.sync_state.get("errors", 0),
            "source_title": source_title,
            "dest_title": dest_title,
        })
        self._log_route_summary(
            "sync",
            copy_message_used=self.sync_state.get("copy_message_used", 0),
            ram_bypass_used=self.sync_state.get("ram_bypass_used", 0),
            tag="info",
        )
        self._log_scope("sync", "Sincronização interrompida.", "warning")
        return {"ok": True, "sync_state": self.sync_state}

    # ── Multi-Group Clone ──

    async def create_forum_topic(self, channel, title):
        try:
            input_channel = await self._get_forum_input_channel(channel, "grupo de destino")
            result = await self.client(CreateForumTopicRequest(
                channel=input_channel,
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
            self._log_scope("forum", f"Falha ao criar tópico '{title}': {e}", "error")
            raise

    async def clone_to_topic(
        self,
        source_entity,
        dest_entity,
        topic_id,
        limit,
        delay,
        anti_flood,
        source_title,
        source_topic_id=None,
    ):
        messages = []
        async for msg in self.client.iter_messages(
            source_entity,
            **self.get_iter_messages_kwargs(limit=limit, reverse=True, reply_to=source_topic_id)
        ):
            messages.append(msg)

        total = len(messages)
        cloned = 0
        ram_bypass_used = 0
        copy_message_used = 0
        anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)
        self._log_scope("topic", f"Clonando '{source_title}' | mensagens: {total}", "info")

        for i, msg in enumerate(messages):
            if self.stop_flag:
                break
            try:
                sent, _ = await self._deliver_message_with_refresh(
                    source_entity,
                    dest_entity,
                    msg,
                    reply_to=topic_id,
                )
                if not sent:
                    cloned += 1
                    continue

                cloned += 1
                if self._last_send_used_ram_bypass:
                    ram_bypass_used += 1
                if self._last_send_used_copy_message:
                    copy_message_used += 1
                if anti_flood_cycle and cloned >= anti_flood_cycle["after_messages"]:
                    pause_seconds = anti_flood_cycle["duration"]
                    self._log_scope(
                        "topic",
                        f"Pausa anti-flood | {self._format_seconds(pause_seconds)}s após {anti_flood_cycle['frequency']} envios.",
                        "warning",
                    )
                    await asyncio.sleep(pause_seconds)
                    anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)
                await asyncio.sleep(delay)
            except FloodWaitError as e:
                self._log_scope("topic", f"FloodWait detectado; aguardando {e.seconds + 5}s.", "error")
                await asyncio.sleep(e.seconds + 5)
                anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)
            except Exception as e:
                self._log_scope("topic", f"Erro na mensagem #{msg.id}: {e}", "error")

        self._log_scope("topic", f"Concluído | {source_title} | mensagens: {cloned}/{total}", "success")
        self._log_route_summary("topic", copy_message_used=copy_message_used, ram_bypass_used=ram_bypass_used, tag="info")
        return {
            "cloned": cloned,
            "ram_bypass_used": ram_bypass_used,
            "copy_message_used": copy_message_used,
        }

    async def rpc_multi_clone(
        self,
        sources=None,
        dest="",
        limit=0,
        delay=0.1,
        pause_every=50,
        pause_duration=2,
        pause_every_min=None,
        pause_every_max=None,
        pause_duration_min=None,
        pause_duration_max=None,
    ):
        if not self.logged_in:
            raise Exception("Não conectado")
        if not sources:
            raise Exception("Nenhum grupo de origem")

        self.stop_flag = False
        self._dialogs_cached = False
        anti_flood = self._resolve_anti_flood_config(
            pause_every=pause_every,
            pause_duration=pause_duration,
            pause_every_min=pause_every_min,
            pause_every_max=pause_every_max,
            pause_duration_min=pause_duration_min,
            pause_duration_max=pause_duration_max,
        )
        dest_entity, dest_topic_id = await self.resolve_target(dest)
        if dest_topic_id:
            raise Exception("Informe apenas o grupo fórum de destino no multi-clone, não um tópico específico.")
        await self._get_forum_input_channel(dest_entity, "grupo de destino")
        total_groups = len(sources)
        total_ram_bypass_used = 0
        total_copy_message_used = 0
        self._log_scope("multi", "Iniciando multi-clone com copy_message antes do fallback legado.", "info")

        for idx, src in enumerate(sources):
            if self.stop_flag:
                break
            src = src.strip()
            if not src:
                continue

            self._log_scope("multi", f"Grupo {idx+1}/{total_groups} | {src}", "info")
            self.emit_progress({
                "type": "multi",
                "group_index": idx,
                "total_groups": total_groups,
                "ram_bypass_used": total_ram_bypass_used,
                "copy_message_used": total_copy_message_used,
            })

            try:
                source_entity, source_topic_id = await self.resolve_target(src)
                source_forum_title = getattr(source_entity, 'title', str(src))
                topic_title = source_forum_title
                source_title = source_forum_title
                if source_topic_id:
                    topic_title = await self.resolve_forum_topic_title(
                        source_entity,
                        source_topic_id,
                        fallback_title=source_forum_title,
                    )
                    source_title = f"{source_forum_title} > {topic_title}"
                topic_id = await self.create_forum_topic(dest_entity, topic_title)
                self._log_scope("multi", f"Tópico criado | {topic_title} (ID {topic_id})", "success")
                result = await self.clone_to_topic(
                    source_entity,
                    dest_entity,
                    topic_id,
                    limit,
                    delay,
                    anti_flood,
                    source_title,
                    source_topic_id,
                )
                total_ram_bypass_used += int((result or {}).get("ram_bypass_used", 0) or 0)
                total_copy_message_used += int((result or {}).get("copy_message_used", 0) or 0)
            except Exception as e:
                self._log_scope("multi", f"Erro no grupo '{src}': {e}", "error")

        self._log_scope("multi", "Multi-clone concluído.", "success")
        self._log_route_summary("multi", copy_message_used=total_copy_message_used, ram_bypass_used=total_ram_bypass_used, tag="info")
        self.emit_progress({
            "type": "multi",
            "status": "done",
            "ram_bypass_used": total_ram_bypass_used,
            "copy_message_used": total_copy_message_used,
        })
        return {
            "ok": True,
            "ram_bypass_used": total_ram_bypass_used,
            "copy_message_used": total_copy_message_used,
        }

    async def get_forum_topics(self, entity):
        topics = []
        try:
            input_channel = await self._get_forum_input_channel(entity, "grupo de origem")
            result = await self.client(GetForumTopicsRequest(
                channel=input_channel, offset_date=0, offset_id=0, offset_topic=0, limit=100
            ))
            if hasattr(result, 'topics'):
                for t in result.topics:
                    if hasattr(t, 'id') and hasattr(t, 'title'):
                        if t.id != 1:  # Skip General topic
                            topics.append({
                                "id": t.id,
                                "title": t.title,
                                "top_message": getattr(t, "top_message", None),
                            })
        except Exception as e:
            self._log_scope("forum", f"Falha ao obter tópicos: {e}", "error")
        return topics

    async def resolve_forum_topic_title(self, entity, topic_id, fallback_title=None):
        topics = await self.get_forum_topics(entity)
        for topic in topics:
            if topic.get("id") == topic_id or topic.get("top_message") == topic_id:
                return topic.get("title") or fallback_title or f"Tópico {topic_id}"

        resolved_title = None
        try:
            async for msg in self.client.iter_messages(
                entity,
                **self.get_iter_messages_kwargs(limit=50, reverse=True, reply_to=topic_id)
            ):
                action = getattr(msg, "action", None)
                if isinstance(action, (MessageActionTopicCreate, MessageActionTopicEdit)):
                    title = getattr(action, "title", None)
                    if title:
                        resolved_title = title
        except Exception:
            pass

        if resolved_title:
            return resolved_title
        if fallback_title:
            return fallback_title
        return getattr(entity, "title", None) or f"Tópico {topic_id}"

    async def clone_topic_messages(
        self,
        source_entity,
        source_topic_id,
        dest_entity,
        dest_topic_id,
        limit,
        delay,
        anti_flood,
        topic_title,
    ):
        messages = []
        async for msg in self.client.iter_messages(
            source_entity, limit=None if limit == 0 else limit,
            reply_to=source_topic_id, reverse=True
        ):
            messages.append(msg)

        total = len(messages)
        cloned = 0
        ram_bypass_used = 0
        copy_message_used = 0
        errors = 0
        anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)
        self._log_scope("topic", f"Tópico '{topic_title}' | mensagens: {total}", "info")

        for i, msg in enumerate(messages):
            if self.stop_flag:
                break
            try:
                sent, _ = await self._deliver_message_with_refresh(
                    source_entity,
                    dest_entity,
                    msg,
                    reply_to=dest_topic_id,
                )
                if not sent:
                    cloned += 1
                    continue

                cloned += 1
                if self._last_send_used_ram_bypass:
                    ram_bypass_used += 1
                if self._last_send_used_copy_message:
                    copy_message_used += 1
                if anti_flood_cycle and cloned >= anti_flood_cycle["after_messages"]:
                    pause_seconds = anti_flood_cycle["duration"]
                    self._log_scope(
                        "topic",
                        f"Pausa anti-flood | {self._format_seconds(pause_seconds)}s após {anti_flood_cycle['frequency']} envios.",
                        "warning",
                    )
                    await asyncio.sleep(pause_seconds)
                    anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)
                await asyncio.sleep(delay)
            except FloodWaitError as e:
                errors += 1
                await asyncio.sleep(e.seconds + 5)
                anti_flood_cycle = self._next_anti_flood_cycle(anti_flood, cloned)
            except Exception as e:
                errors += 1
                self._log_scope("topic", f"Erro na mensagem #{msg.id}: {e}", "error")

        self._log_scope("topic", f"Concluído | {topic_title} | mensagens: {cloned}/{total} | erros: {errors}", "success")
        self._log_route_summary("topic", copy_message_used=copy_message_used, ram_bypass_used=ram_bypass_used, tag="info")
        return {
            "cloned": cloned,
            "ram_bypass_used": ram_bypass_used,
            "copy_message_used": copy_message_used,
            "errors": errors,
        }

    async def rpc_forum_clone(
        self,
        source="",
        dest="",
        limit=0,
        delay=0.1,
        pause_every=50,
        pause_duration=2,
        pause_every_min=None,
        pause_every_max=None,
        pause_duration_min=None,
        pause_duration_max=None,
    ):
        if not self.logged_in:
            raise Exception("Não conectado")

        self.stop_flag = False
        self._dialogs_cached = False
        anti_flood = self._resolve_anti_flood_config(
            pause_every=pause_every,
            pause_duration=pause_duration,
            pause_every_min=pause_every_min,
            pause_every_max=pause_every_max,
            pause_duration_min=pause_duration_min,
            pause_duration_max=pause_duration_max,
        )

        source_entity, source_topic_id = await self.resolve_target(source)
        dest_entity, dest_topic_id = await self.resolve_target(dest)
        if dest_topic_id:
            raise Exception("Informe apenas o grupo fórum de destino na clonagem de fórum, não um tópico específico.")
        await self._get_forum_input_channel(dest_entity, "grupo de destino")
        if not source_topic_id:
            await self._get_forum_input_channel(source_entity, "grupo de origem")

        if source_topic_id:
            source_topic_title = await self.resolve_forum_topic_title(
                source_entity,
                source_topic_id,
                fallback_title=getattr(source_entity, "title", None),
            )
            source_topics = [{"id": source_topic_id, "title": source_topic_title}]
        else:
            source_topics = await self.get_forum_topics(source_entity)
        total_topics = len(source_topics)
        total_ram_bypass_used = 0
        total_copy_message_used = 0
        total_errors = 0
        self._log_scope("forum", f"Tópicos encontrados no fórum de origem: {total_topics}", "info")

        for idx, topic in enumerate(source_topics):
            if self.stop_flag:
                break

            self._log_scope("forum", f"Tópico {idx+1}/{total_topics} | {topic['title']}", "info")
            self.emit_progress({
                "type": "forum", "topic_index": idx, "total_topics": total_topics,
                "topic_title": topic['title'],
                "ram_bypass_used": total_ram_bypass_used,
                "copy_message_used": total_copy_message_used,
                "errors": total_errors,
            })

            try:
                new_topic_id = await self.create_forum_topic(dest_entity, topic['title'])
                self._log_scope("forum", f"Tópico criado | {topic['title']} (ID {new_topic_id})", "success")
                topic_result = await self.clone_topic_messages(
                    source_entity, topic['id'], dest_entity, new_topic_id,
                    limit, delay, anti_flood, topic['title']
                )
                total_ram_bypass_used += int((topic_result or {}).get("ram_bypass_used", 0) or 0)
                total_copy_message_used += int((topic_result or {}).get("copy_message_used", 0) or 0)
                total_errors += int((topic_result or {}).get("errors", 0) or 0)
            except Exception as e:
                total_errors += 1
                self._log_scope("forum", f"Erro no tópico '{topic['title']}': {e}", "error")

        self._log_scope("forum", "Clonagem de fórum concluída.", "success")
        self._log_route_summary("forum", copy_message_used=total_copy_message_used, ram_bypass_used=total_ram_bypass_used, tag="info")
        self.emit_progress({
            "type": "forum",
            "status": "done",
            "ram_bypass_used": total_ram_bypass_used,
            "copy_message_used": total_copy_message_used,
            "errors": total_errors,
            "total_topics": total_topics,
        })
        return {
            "ok": True,
            "ram_bypass_used": total_ram_bypass_used,
            "copy_message_used": total_copy_message_used,
            "errors": total_errors,
        }

# ── Main Loop ──

async def main():
    server = HaumeaServer()
    server.loop = asyncio.get_running_loop()

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
            if req.get("method") == "shutdown":
                await server.handle(req)
                break
            # Handle in background to not block stdin reading
            asyncio.create_task(server.handle(req))
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -1, "message": str(e)}}),
                  flush=True)


if __name__ == "__main__":
    asyncio.run(main())
