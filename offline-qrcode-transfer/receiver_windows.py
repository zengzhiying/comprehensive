#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
receiver_windows.py —— 二维码单向传文件 · 接收端（在外网机器上运行）

用途
    内网机器用 sender_windows.py 把文件打成二维码轮播；那台机器的画面通过远程桌面
    显示在本机屏幕上，本脚本直接对屏幕上的一块区域连续截屏、解码、按序号拼回文件。
    不需要摄像头，也不需要和对方有任何网络连接。

依赖
    Python 3.8+（Windows 官方安装包自带 tkinter）
    pip install mss pillow opencv-python-headless
    pip install pyzbar        # 可选但强烈建议，解码更稳（Windows 的 wheel 自带 zbar 动态库）

运行
    python receiver_windows.py

协议（必须与 sender_windows.py 完全一致）
    起始帧  QRT1|S|<会话号>|<起始序号>|<总包数>|<分包字节>|<文件字节>|<b64(文件名)>|<crc32>
    数据帧  QRT1|D|<会话号>|<序号>|<crc32:8位小写hex>|<b64(分片数据)>
    结束帧  QRT1|E|<总包数>|<文件字节>|<sha256>|<b64(文件名)>|<crc32>

    三种帧都带校验码：数据帧的 crc32 在中间、护着序号和数据；起始帧/结束帧的 crc32 在
    最后，覆盖它前面的整串内容。校验不过的帧一律当作「没解出来」丢掉，绝不会拿着
    错参数去建会话，也绝不会把好数据误判成校验失败。

接收规则（严格顺序）
    · 只收「正好是当前缺的那个序号」的包；比它小的当重复帧丢弃（自动去重）；
    · 比它大的说明中间丢包了 —— 立刻报警并停在缺失序号上死等，后续数据一律不接收；
    · 操作员看到报警后，把发送端的【起始序号】改成缺失的序号、点【重发起始帧】，
      接收端收到新的起始帧就会从那个序号继续，前面的数据不用重传；
    · 只有 0 ~ 总包数-1 全部收齐，并且整文件 SHA-256 与结束帧一致，才会写出最终文件；
      否则报错，不产生任何「看起来像成功」的残缺文件。

断点续传
    数据边收边写进 <文件名>.qrtpart，进度写在 <文件名>.qrtstate。
    本程序被关掉、崩掉、重启都不影响：下次收到同一个文件的起始帧会自动接着收。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import zlib
from tkinter import filedialog, messagebox, ttk

# 这些库只有真正开始扫描时才需要；缺失时给出中文安装提示，不影响本文件被导入/测试
try:
    from PIL import Image, ImageTk
except ImportError:                                    # pragma: no cover
    Image = ImageTk = None
try:
    from PIL import ImageGrab                          # 没有 mss 时的截屏退路
except ImportError:                                    # pragma: no cover
    ImageGrab = None
try:
    import mss
except ImportError:                                    # pragma: no cover
    mss = None
try:
    import cv2
except ImportError:                                    # pragma: no cover
    cv2 = None
try:
    from pyzbar import pyzbar
    try:
        from pyzbar.pyzbar import ZBarSymbol
        PYZBAR_SYMBOLS = [ZBarSymbol.QRCODE]           # 只找二维码，别去扫 databar 那些
    except Exception:                                  # pragma: no cover
        PYZBAR_SYMBOLS = None
except Exception:                                      # pragma: no cover
    pyzbar = None
    PYZBAR_SYMBOLS = None

# ---------------------------------------------------------------------------
# 协议定义（必须与 sender_windows.py 保持一致）
# ---------------------------------------------------------------------------

PROTO_VERSION = "QRT1"
FRAME_START = "S"
FRAME_DATA = "D"
FRAME_END = "E"

STATE_SUFFIX = ".qrtstate"
PART_SUFFIX = ".qrtpart"
STATE_VERSION = 1

# 起始帧参数的上限：位图分配和文件预占都按这些数来，不能让一个荒唐的参数
# （或者一次误解码）把程序带进沟里。2000 万包足够 1 GB 文件用 50 字节分包了。
MAX_TOTAL_CHUNKS = 20_000_000
MAX_FILE_SIZE = 8 * 1024 ** 3

# _try_load_existing 的第三种返回值：同名旧进度的参数对不上，而操作员选择保留它
_BLOCKED = object()

# 连续解出同一帧多少次才认账，防止极低概率的误码蒙混过关
CONFIRM_DEFAULT = 2
# 采样帧率（每秒截屏解码几次）
FPS_DEFAULT = 8
# 结束帧重复校验的最小间隔（秒），避免同一个结束帧被反复触发整文件哈希
END_RECHECK_COOLDOWN = 1.5
# 超过这么多秒没扫到任何有效帧就提示操作员（发送端可能停了或被挡住）
STALL_HINT_SECONDS = 15


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def split_trailing_crc(text: str):
    """起始帧/结束帧的末尾是一个覆盖整串内容的 crc32。

    返回去掉 crc 的部分；crc 格式不对或对不上都返回 None（这一帧就当作没解出来）。
    """
    head, sep, tail = text.rpartition("|")
    if not sep or len(tail) != 8:
        return None
    try:
        want = int(tail, 16)
        raw = head.encode("ascii")      # 非 ASCII 字符一律判为非法帧，不能 ignore 掉再算 crc
    except (ValueError, UnicodeEncodeError):
        return None
    if (zlib.crc32(raw) & 0xFFFFFFFF) != want:
        return None
    return head


def parse_frame(text: str):
    """解析一帧。不是本协议 / 结构不对 / 校验码对不上 → None。"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    parts = text.split("|")
    if len(parts) < 3 or parts[0] != PROTO_VERSION:
        return None
    kind = parts[1]

    if kind in (FRAME_START, FRAME_END):
        head = split_trailing_crc(text)
        if head is None:
            return None
        parts = head.split("|")

    if kind == FRAME_DATA:
        if len(parts) != 6:
            return None
        session = parts[2]
        try:
            index = int(parts[3])
        except ValueError:
            return None
        if index < 0 or len(parts[4]) != 8:
            return None
        body = parts[5]
        try:
            payload = b64d(body)
        except Exception:
            return None
        want = "%08x" % (zlib.crc32(
            ("%s|%d|%s" % (session, index, body)).encode("ascii")) & 0xFFFFFFFF)
        return {"kind": FRAME_DATA, "session": session, "index": index, "payload": payload,
                "crc_ok": want == parts[4].lower(), "raw": text}

    if kind == FRAME_START:
        if len(parts) != 8:
            return None
        try:
            start_index = int(parts[3])
            total = int(parts[4])
            chunk_size = int(parts[5])
            file_size = int(parts[6])
            name = b64d(parts[7]).decode("utf-8")
        except Exception:
            return None
        if not parts[2] or total < 1 or chunk_size < 1 or file_size < 0 or start_index < 0:
            return None
        return {"kind": FRAME_START, "session": parts[2], "start_index": start_index,
                "total": total, "chunk_size": chunk_size, "file_size": file_size,
                "file_name": name, "raw": text}

    if kind == FRAME_END:
        if len(parts) != 6:
            return None
        try:
            total = int(parts[2])
            file_size = int(parts[3])
            name = b64d(parts[5]).decode("utf-8")
        except Exception:
            return None
        sha = parts[4].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            return None
        return {"kind": FRAME_END, "total": total, "file_size": file_size,
                "sha256": sha, "file_name": name, "raw": text}

    return None


def sanitize_file_name(name: str) -> str:
    """把对端给的文件名收拾成一个安全的、只在本目录下的文件名。"""
    name = os.path.basename(str(name).replace("\\", "/"))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        name = "received.bin"
    return name[:120]


def unique_path(path: str) -> str:
    """目标已存在时，改成 name (1).ext 这种形式，绝不覆盖已有文件。"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 1000):
        candidate = "%s (%d)%s" % (base, i, ext)
        if not os.path.exists(candidate):
            return candidate
    return "%s (%d)%s" % (base, int(time.time()), ext)


def human_size(n: float) -> str:
    for unit, base in (("B", 1), ("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3)):
        if n < base * 1024 or unit == "GB":
            return ("%d B" % n) if base == 1 else ("%.1f %s" % (n / base, unit))
    return "%d B" % n


def human_time(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return "%d 秒" % seconds
    if seconds < 3600:
        return "%d 分 %02d 秒" % (seconds // 60, seconds % 60)
    return "%d 小时 %02d 分" % (seconds // 3600, (seconds % 3600) // 60)


# ---------------------------------------------------------------------------
# 会话：数据落盘 + 进度落盘
# ---------------------------------------------------------------------------

class Session:
    """一个文件的接收会话。数据写在 <名字>.qrtpart，元数据写在 <名字>.qrtstate。"""

    def __init__(self, outdir: str, file_name: str):
        self.outdir = outdir
        self.file_name = file_name
        self.part_path = os.path.join(outdir, file_name + PART_SUFFIX)
        self.state_path = os.path.join(outdir, file_name + STATE_SUFFIX)
        self.session = ""
        self.file_size = 0
        self.chunk_size = 0
        self.total = 0
        self.sha256_hex = ""
        self.bits = bytearray()
        self.count = 0
        self.expected = 0
        self._fp = None
        self._dirty = 0

    # -- 位图 ---------------------------------------------------------------

    def has(self, index: int) -> bool:
        return bool(self.bits[index >> 3] & (1 << (index & 7)))

    def _mark(self, index: int):
        self.bits[index >> 3] |= 1 << (index & 7)
        self.count += 1

    def first_missing(self, start: int = 0) -> int:
        i = max(0, start)
        while i < self.total and self.has(i):
            i += 1
        return i

    @property
    def complete(self) -> bool:
        return self.count >= self.total

    def missing_desc(self, max_ranges: int = 8) -> str:
        """缺失的包描述成 '37~42、50' 这样。包数可能上百万，所以凑够 max_ranges 段就收手。"""
        total = self.total
        ranges = []
        i = 0
        while i < total and len(ranges) <= max_ranges:
            if self.has(i):
                i += 1
                continue
            start = i
            while i < total and not self.has(i):
                i += 1
            ranges.append((start, i - 1))
        if not ranges:
            return ""
        shown = "、".join("%d" % a if a == b else "%d~%d" % (a, b) for a, b in ranges[:max_ranges])
        if len(ranges) > max_ranges:
            shown += " …（还有更多缺包）"
        return shown

    # -- 生命周期 -----------------------------------------------------------

    def create(self, session: str, file_size: int, chunk_size: int, total: int):
        self.session = session
        self.file_size = file_size
        self.chunk_size = chunk_size
        self.total = total
        # 位图和文件大小都已经过 _on_start 的上限校验，这里直接分配
        self.bits = bytearray((total + 7) // 8)
        self.count = 0
        self.expected = 0
        os.makedirs(self.outdir, exist_ok=True)
        if os.path.exists(self.part_path):
            # 有 .qrtpart 却没有能对上的 .qrtstate，这份数据已经无法续传了，
            # 但也不该静默截断掉，改个名留着
            backup = unique_path(self.part_path + ".old")
            try:
                os.replace(self.part_path, backup)
            except OSError:
                pass
        self._fp = open(self.part_path, "w+b")
        self._fp.truncate(file_size)          # 先占好大小，后面按偏移写入
        self._fp.flush()
        self.save_state(force=True)

    def ensure_open(self):
        """兜底：句柄万一被关掉了（比如中途出过错），重新打开，别让后续写入直接崩。"""
        if self._fp is None:
            self._fp = open(self.part_path, "r+b")

    def reset_progress(self):
        """整文件校验失败后把这次会话的数据作废，好让发送端从第 0 包重新完整传一遍。"""
        self.close()
        with open(self.part_path, "w+b") as fp:
            fp.truncate(self.file_size)
        self._fp = open(self.part_path, "r+b")
        self.bits = bytearray((self.total + 7) // 8)
        self.count = 0
        self.expected = 0
        self.sha256_hex = ""
        self.save_state(force=True)

    @classmethod
    def load(cls, state_path: str):
        with open(state_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if data.get("state_version") != STATE_VERSION:
            return None
        # 以状态文件实际所在的目录为准，而不是文件里记的 outdir：
        # 用户把 .qrtpart/.qrtstate 一起拷到别的目录时，也能接着收
        outdir = os.path.dirname(os.path.abspath(state_path)) or data.get("outdir", ".")
        obj = cls(outdir, data["file_name"])
        obj.session = data["session"]
        obj.file_size = data["file_size"]
        obj.chunk_size = data["chunk_size"]
        obj.total = data["total"]
        obj.sha256_hex = data.get("sha256", "")
        if obj.total < 1 or obj.file_size < 0 or obj.chunk_size < 1:
            return None
        obj.bits = bytearray(base64.b64decode(data["bits"]))
        need = (obj.total + 7) // 8
        del obj.bits[need:]                      # 多出来的字节直接丢掉
        if len(obj.bits) < need:
            obj.bits.extend(b"\x00" * (need - len(obj.bits)))
        if need and obj.total % 8:
            obj.bits[-1] &= (1 << (obj.total % 8)) - 1   # 末字节里超出总包数的位清掉
        obj.count = sum(bin(b).count("1") for b in obj.bits)   # 以位图为准，不信文件里写的 count
        obj.expected = obj.first_missing(0)
        if not os.path.exists(obj.part_path):
            return None
        obj._fp = open(obj.part_path, "r+b")
        return obj

    def matches(self, session: str, file_size: int, chunk_size: int, total: int) -> bool:
        return (self.session == session and self.file_size == file_size
                and self.chunk_size == chunk_size and self.total == total)

    def save_state(self, force: bool = False):
        self._dirty += 1
        if not force and self._dirty < 8:
            return
        self._dirty = 0
        payload = {
            "state_version": STATE_VERSION,
            "outdir": self.outdir,
            "file_name": self.file_name,
            "session": self.session,
            "file_size": self.file_size,
            "chunk_size": self.chunk_size,
            "total": self.total,
            "sha256": self.sha256_hex,
            "received": self.count,
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "bits": base64.b64encode(bytes(self.bits)).decode("ascii"),
        }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(payload, fp)
        os.replace(tmp, self.state_path)      # 原子替换，断电也不会写出半个状态文件

    def write_chunk(self, index: int, payload: bytes):
        self.ensure_open()
        self._fp.seek(index * self.chunk_size)
        self._fp.write(payload)
        self._fp.flush()
        self._mark(index)
        self.expected = self.first_missing(self.expected)
        self.save_state()

    def finish(self) -> str:
        """收齐并校验通过后：把 .qrtpart 变成真正的文件，返回最终路径。"""
        self.close()
        dest = unique_path(os.path.join(self.outdir, self.file_name))
        os.replace(self.part_path, dest)
        try:
            os.remove(self.state_path)
        except OSError:
            pass
        return dest

    def discard(self):
        """彻底放弃这次传输（数据和进度一起删）。"""
        self.close()
        for path in (self.part_path, self.state_path):
            try:
                os.remove(path)
            except OSError:
                pass

    def close(self):
        if self._fp is not None:
            try:
                self._fp.flush()
                os.fsync(self._fp.fileno())
            except OSError:
                pass
            try:
                self._fp.close()
            except OSError:
                pass
            self._fp = None

    def sha256_of_part(self) -> str:
        digest = hashlib.sha256()
        with open(self.part_path, "rb") as fp:
            for block in iter(lambda: fp.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()


def list_pending_sessions(outdir: str):
    """列出输出目录里没传完的会话，界面上用来提示/恢复。"""
    result = []
    try:
        names = sorted(os.listdir(outdir))
    except OSError:
        return result
    for name in names:
        if not name.endswith(STATE_SUFFIX):
            continue
        path = os.path.join(outdir, name)
        try:
            session = Session.load(path)
        except Exception:
            session = None
        if session is not None:
            result.append((session, path))
    return result


# ---------------------------------------------------------------------------
# 接收状态机（不依赖界面/截屏，可独立测试）
# ---------------------------------------------------------------------------

STATUS_IDLE = "idle"
STATUS_RECEIVING = "receiving"
STATUS_GAP = "gap"
STATUS_DONE = "done"


class ReceiverCore:

    def __init__(self, outdir: str, log=None, on_conflict=None, on_change=None):
        self.outdir = outdir
        self.log = log or (lambda msg, level="info": None)
        self.on_conflict = on_conflict or (lambda info: True)
        self.on_change = on_change or (lambda: None)
        self.session: Session | None = None
        self.status = STATUS_IDLE
        self.gap_expected = None       # 卡在哪个序号
        self.gap_got = None
        self.saved_path = None
        self.stats = {"accepted": 0, "duplicate": 0, "bad_crc": 0, "invalid": 0,
                      "gap": 0, "start": 0, "end": 0, "wrong_session": 0}
        self._last_end_check = 0.0

    # -- 对外接口 -----------------------------------------------------------

    def feed(self, text: str) -> dict:
        parsed = parse_frame(text)
        if parsed is None:
            self.stats["invalid"] += 1
            return {"status": "invalid"}
        if parsed["kind"] == FRAME_START:
            return self._on_start(parsed)
        if parsed["kind"] == FRAME_DATA:
            return self._on_data(parsed)
        return self._on_end(parsed)

    def reset(self):
        if self.session is not None:
            self.session.close()
        self.session = None
        self.status = STATUS_IDLE
        self.gap_expected = None
        self.gap_got = None
        self.saved_path = None
        self.on_change()

    # -- 起始帧 -------------------------------------------------------------

    def _on_start(self, frame: dict) -> dict:
        name = sanitize_file_name(frame["file_name"])
        total, chunk_size, file_size = frame["total"], frame["chunk_size"], frame["file_size"]
        session = frame["session"]

        # 参数自洽性检查：总包数必须正好装下这个文件
        expect_total = max(1, -(-file_size // chunk_size)) if file_size else 1
        if expect_total != total:
            self.log("起始帧参数不自洽：文件 %d 字节 / 分包 %d 字节 应该是 %d 包，但帧里写的是 %d 包"
                     % (file_size, chunk_size, expect_total, total), "error")
            return {"status": "bad_start"}

        # 上限校验：起始帧虽然是带 crc 的，但也不能让一个荒唐的参数把程序带进沟里
        # （位图分配、文件预占都要按这个数来）
        if total > MAX_TOTAL_CHUNKS or file_size > MAX_FILE_SIZE:
            self.log("起始帧参数超出上限：总包数 %d（上限 %d）、文件 %s（上限 %s），拒绝"
                     % (total, MAX_TOTAL_CHUNKS, human_size(file_size),
                        human_size(MAX_FILE_SIZE)), "error")
            return {"status": "bad_start"}

        if self.session is not None and self.session.matches(session, file_size, chunk_size, total) \
                and self.status != STATUS_DONE:
            # 同一个文件又发了起始帧：这就是「续传」信号
            self.stats["start"] += 1
            self.gap_expected = None
            self.gap_got = None
            self.status = STATUS_RECEIVING
            self.session.expected = self.session.first_missing(0)
            self.log("收到起始帧：发送端从第 %d 包开始，本机已收 %d/%d 包，接着等第 %d 包"
                     % (frame["start_index"], self.session.count, total, self.session.expected), "info")
            self._warn_start_index(frame["start_index"])
            self.on_change()
            return {"status": "resumed", "expected": self.session.expected}

        # 换文件 / 换参数：先把旧会话收尾
        if self.session is not None:
            self.session.close()

        loaded = self._try_load_existing(name, session, file_size, chunk_size, total)
        if loaded is _BLOCKED:
            # 操作员选择保留旧进度：这次不能收，会话对象也清掉，等人工处理
            self.session = None
            self.status = STATUS_IDLE
            self.on_change()
            return {"status": "conflict_blocked"}
        if loaded is None:
            candidate = Session(self.outdir, name)
            try:
                candidate.create(session, file_size, chunk_size, total)
            except OSError as exc:
                # 磁盘满 / 目录不可写 / 同名目录挡路等，不能让半初始化的会话留在身上
                self.log("无法建立接收文件：%s（%s）" % (exc, candidate.part_path), "error")
                self.session = None
                self.status = STATUS_IDLE
                self.on_change()
                return {"status": "create_failed"}
            self.session = candidate
            self.log("新传输：%s（%s，%d 包 × %d 字节，会话 %s）"
                     % (name, human_size(file_size), total, chunk_size, session), "ok")
        else:
            self.session = loaded
            self.log("发现未完成的传输，已接着收：%s，已收 %d/%d 包"
                     % (name, loaded.count, total), "ok")

        self.stats["start"] += 1
        self.saved_path = None
        self.gap_expected = None
        self.gap_got = None
        self.status = STATUS_RECEIVING
        self.session.expected = self.session.first_missing(0)
        self._warn_start_index(frame["start_index"])
        self.on_change()
        return {"status": "started", "expected": self.session.expected}

    def _warn_start_index(self, start_index: int):
        """发送端从中间某包开始，但本机前面还缺包 —— 必须提醒，否则最后一定校验失败。"""
        assert self.session is not None
        expected = self.session.expected
        if start_index > expected:
            self.log("⚠ 发送端从第 %d 包开始，但本机第 %d 包还没有数据；"
                     "若这是想跳过前面，最后会因缺包失败，请让发送端从第 %d 包开始。"
                     % (start_index, expected, expected), "warn")
        elif start_index < expected:
            self.log("发送端从第 %d 包开始，第 %d 包之前的数据本机已有，会按重复帧跳过"
                     % (start_index, expected), "info")

    def _try_load_existing(self, name, session, file_size, chunk_size, total):
        """找找输出目录里有没有同一个文件的未完成进度。

        返回 Session（接着收）、None（按新传输处理）或 _BLOCKED（操作员选择保留旧进度）。
        """
        state_path = os.path.join(self.outdir, name + STATE_SUFFIX)
        if not os.path.exists(state_path):
            return None
        try:
            existing = Session.load(state_path)
        except Exception as exc:
            self.log("旧进度文件读不出来（%s），按新传输处理" % exc, "warn")
            return None
        if existing is None:
            return None
        if existing.matches(session, file_size, chunk_size, total):
            return existing
        info = {"name": name, "old_session": existing.session, "new_session": session,
                "old_size": existing.file_size, "new_size": file_size,
                "old_chunk": existing.chunk_size, "new_chunk": chunk_size,
                "old_total": existing.total, "new_total": total,
                "received": existing.count}
        if self.on_conflict(info):
            self.log("同名但参数不一致（内容或分包大小变了），丢弃旧进度，重新开始", "warn")
            existing.discard()
            return None
        # 保留旧进度：这次传输就没法收了（参数对不上，硬收会把数据写乱）。
        # 会话对象先关掉，免得它挂着文件句柄
        self.log("已按你的选择保留旧进度，本次传输无法进行。"
                 "要接着传旧文件请把发送端换回那个文件；要放弃旧进度请点【放弃本次会话】。", "warn")
        existing.close()
        return _BLOCKED

    # -- 数据帧 -------------------------------------------------------------

    def _on_data(self, frame: dict) -> dict:
        if self.session is None or self.status in (STATUS_IDLE, STATUS_DONE):
            return {"status": "no_session"}
        if not frame["crc_ok"]:
            self.stats["bad_crc"] += 1
            self.log("丢弃一个校验码不对的帧（序号 %d），多半是屏幕压缩导致的误码" % frame["index"],
                     "warn")
            return {"status": "bad_crc"}

        session = self.session
        index = frame["index"]

        # 会话号对不上 = 这是「另一次传输」的数据帧。
        # 不加这道闸的话：换文件后如果起始帧没扫到，新文件的数据会被按偏移写进旧文件
        # 没传完的会话里，而结束帧的总包数/文件大小又对得上、整文件 SHA 也自洽
        # （字节就是新文件本身），最后会用旧文件名存下新文件的内容还报「成功」。
        if frame["session"] != session.session:
            self.stats["wrong_session"] += 1
            self.log("✖ 这一帧属于另一次传输（会话 %s…），本机正在收的是 %s…（会话 %s…）。"
                     "已丢弃。请确认发送端选的文件，并重新发送起始帧。"
                     % (frame["session"][:8], session.file_name, session.session[:8]), "error")
            return {"status": "wrong_session", "got": frame["session"],
                    "want": session.session}

        if index >= session.total:
            self.stats["invalid"] += 1
            self.log("收到越界序号 %d（总包数 %d），忽略" % (index, session.total), "warn")
            return {"status": "invalid"}

        # 长度校验：除最后一包外都必须正好是一个分片
        want_len = session.chunk_size if index < session.total - 1 \
            else session.file_size - index * session.chunk_size
        if len(frame["payload"]) != want_len:
            self.stats["bad_crc"] += 1
            self.log("第 %d 包长度不对（收到 %d 字节，应为 %d 字节），丢弃"
                     % (index, len(frame["payload"]), want_len), "warn")
            return {"status": "bad_crc"}

        if index < session.expected:
            self.stats["duplicate"] += 1
            if self.status == STATUS_GAP and index < (self.gap_expected or 0):
                pass                    # 缺包期间收到更早的重复帧，静默忽略
            return {"status": "duplicate", "index": index}

        if index > session.expected:
            self.stats["gap"] += 1
            self.gap_expected = session.expected
            self.gap_got = index
            self.status = STATUS_GAP
            self.log("✖ 缺包：正在等第 %d 包，却收到了第 %d 包 —— 已停止接收后续数据。"
                     "请把发送端的【起始序号】改成 %d 并点【重发起始帧】。"
                     % (session.expected, index, session.expected), "error")
            self.on_change()
            return {"status": "gap", "expected": session.expected, "got": index}

        session.write_chunk(index, frame["payload"])
        self.stats["accepted"] += 1
        if self.status == STATUS_GAP:
            self.log("缺的第 %d 包已补上，继续接收" % index, "ok")
        self.gap_expected = None
        self.gap_got = None
        self.status = STATUS_RECEIVING
        self.on_change()
        return {"status": "accepted", "index": index, "expected": session.expected,
                "received": session.count, "total": session.total}

    # -- 结束帧 -------------------------------------------------------------

    def _on_end(self, frame: dict) -> dict:
        if self.session is None:
            return {"status": "no_session"}
        session = self.session
        if self.status == STATUS_DONE:
            return {"status": "already_done"}

        now = time.monotonic()
        if now - self._last_end_check < END_RECHECK_COOLDOWN:
            return {"status": "end_cooldown"}      # 同一个结束帧被反复扫到，不必反复校验
        self._last_end_check = now
        self.stats["end"] += 1

        if (frame["total"], frame["file_size"]) != (session.total, session.file_size):
            self.log("结束帧与起始帧对不上（包数 %d/%d，大小 %d/%d），忽略"
                     % (frame["total"], session.total, frame["file_size"], session.file_size),
                     "error")
            return {"status": "end_mismatch"}

        if session.sha256_hex and session.sha256_hex != frame["sha256"]:
            self.log("结束帧的 SHA-256 与之前收到的结束帧不一致，忽略", "error")
            return {"status": "end_mismatch"}
        session.sha256_hex = frame["sha256"]

        if not session.complete:
            missing = session.missing_desc()
            expected = session.expected
            self.log("✖ 收到结束帧，但还缺 %d 包没收到：%s —— 不会保存文件。"
                     "请让发送端把【起始序号】改成第 %d 包后重发。"
                     % (session.total - session.count, missing, expected), "error")
            self.status = STATUS_GAP
            self.gap_expected = expected
            self.on_change()
            return {"status": "incomplete", "missing": missing, "expected": expected}

        self.log("包已收齐，正在校验整文件 SHA-256…", "info")
        actual = session.sha256_of_part()
        if actual != frame["sha256"]:
            # 数据不可信：把这次会话的进度整个作废，好让发送端从第 0 包重新完整传一遍。
            # 不作废的话位图是满的、expected 已经到末尾，重传的每一包都会被当成重复帧丢掉，
            # 日志里那句「重新完整传输」就永远走不通了。
            self.log("✖ 整文件校验失败：期望 %s…，实际 %s… —— 数据不可信，本次传输作废。"
                     "已清空进度，请让发送端把【起始序号】改回 0 重新完整传一遍。"
                     % (frame["sha256"][:16], actual[:16]), "error")
            try:
                session.reset_progress()
            except OSError as exc:
                self.log("清空进度时出错：%s，请点【放弃本次会话】" % exc, "error")
            self.status = STATUS_RECEIVING
            self.gap_expected = 0
            self.gap_got = None
            self._last_end_check = 0.0
            self.on_change()
            return {"status": "hash_mismatch", "expected": frame["sha256"], "actual": actual}

        try:
            dest = session.finish()
        except OSError as exc:
            self.log("写文件失败：%s" % exc, "error")
            return {"status": "save_failed", "error": str(exc)}

        self.status = STATUS_DONE
        self.saved_path = dest
        self.log("✔ 传输完成并校验通过，已保存：%s（%s）"
                 % (dest, human_size(session.file_size)), "ok")
        self.on_change()
        return {"status": "completed", "path": dest}

    # -- 供界面显示 ---------------------------------------------------------

    def progress(self):
        if self.session is None:
            return None
        s = self.session
        # 直接用在 write_chunk 里增量维护的 expected，不要再从 0 扫一遍位图：
        # 每收一包都 O(总包数) 的话，整体就是 O(总包数²)，传输后段界面会卡死
        return {"name": s.file_name, "received": s.count, "total": s.total,
                "expected": s.expected, "size": s.file_size,
                "chunk": s.chunk_size, "session": s.session, "status": self.status}


# ---------------------------------------------------------------------------
# 截屏 + 解码
# ---------------------------------------------------------------------------

class ScreenSource:
    """屏幕截取。优先 mss（快、支持多显示器），退而求其次用 Pillow 的 ImageGrab。"""

    def __init__(self):
        self._sct = None
        self._monitors = []
        self.backend = None

    def open(self):
        """注意：mss 的实例不能跨线程用，所以本对象在哪个线程用就在哪个线程 open()。"""
        if self.backend is not None:
            return                          # 已经打开过，别重复占资源
        if mss is not None:
            self._sct = mss.mss()
            self._monitors = list(self._sct.monitors)
            self.backend = "mss"
            return
        if ImageGrab is not None:
            self.backend = "pillow"
            size = _screen_size()
            self._monitors = [{"left": 0, "top": 0, "width": size[0], "height": size[1]}]
            return
        raise RuntimeError("没有可用的截屏后端，请执行：pip install mss pillow")

    @property
    def monitors(self):
        return self._monitors

    def virtual_screen(self):
        """整个虚拟桌面（所有显示器拼起来）的矩形。"""
        if self._monitors:
            m = self._monitors[0]
            return {"left": m["left"], "top": m["top"],
                    "width": m["width"], "height": m["height"]}
        w, h = _screen_size()
        return {"left": 0, "top": 0, "width": w, "height": h}

    def grab(self, region):
        """region 为 {left, top, width, height}；返回 (PIL 图像, 原始字节签名)。"""
        if self.backend == "mss":
            shot = self._sct.grab(region)
            raw = shot.rgb                       # 已经转好 RGB，字节序也对了
            image = Image.frombytes("RGB", shot.size, raw)
            return image, zlib.crc32(raw)
        bbox = (region["left"], region["top"],
                region["left"] + region["width"], region["top"] + region["height"])
        image = ImageGrab.grab(bbox=bbox)
        image = image.convert("RGB")
        return image, zlib.crc32(image.tobytes())

    def close(self):
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
        # backend 要清掉，否则停止扫描后再点开始，open() 会以为已经打开而直接返回，
        # 结果 _sct 是空的。_monitors 保留着，界面查显示器尺寸还要用。
        self.backend = None


def _screen_size():
    """屏幕尺寸。已经有 Tk 主窗口就复用它，不要另起一个解释器。"""
    root = getattr(tk, "_default_root", None)
    if root is not None:
        try:
            return (root.winfo_screenwidth(), root.winfo_screenheight())
        except tk.TclError:
            pass
    try:
        tmp = tk.Tk()
        tmp.withdraw()
        size = (tmp.winfo_screenwidth(), tmp.winfo_screenheight())
        tmp.destroy()
        return size
    except Exception:
        return (1920, 1080)


class QrDecoder:
    """二维码解码。pyzbar 优先，opencv 兜底，两个都用不了就直接报错。"""

    def __init__(self):
        self.backends = []
        if pyzbar is not None and Image is not None:
            self.backends.append("pyzbar")
        if cv2 is not None:
            self.backends.append("opencv")
        if not self.backends:
            raise RuntimeError(
                "没有可用的二维码解码库，请执行：\n"
                "    pip install opencv-python-headless\n"
                "    pip install pyzbar        （可选，识别更稳）")
        self._detector = cv2.QRCodeDetector() if cv2 is not None else None
        self._multi = cv2 is not None and hasattr(self._detector, "detectAndDecodeMulti")

    def decode(self, image):
        """返回 [{'text': str, 'rect': (x, y, w, h) 或 None}, ...]"""
        results = []
        if "pyzbar" in self.backends:
            try:
                # 限定只解二维码：zbar 默认会连 databar/code128 一起扫，又慢又会打内部警告
                found = pyzbar.decode(image, symbols=PYZBAR_SYMBOLS) \
                    if PYZBAR_SYMBOLS else pyzbar.decode(image)
                for sym in found:
                    try:
                        text = sym.data.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                    rect = None
                    if sym.rect is not None:
                        rect = (sym.rect.left, sym.rect.top, sym.rect.width, sym.rect.height)
                    results.append({"text": text, "rect": rect})
            except Exception:
                pass
        if not results and "opencv" in self.backends:
            results.extend(self._decode_cv2(image))
        return results

    def _decode_cv2(self, image):
        import numpy as np
        arr = np.asarray(image.convert("L"))
        out = []
        try:
            if self._multi:
                ok, texts, points, _ = self._detector.detectAndDecodeMulti(arr)
                if ok and texts:
                    for text, pts in zip(texts, points or []):
                        if text:
                            out.append({"text": text, "rect": _rect_from_points(pts)})
            if not out:
                text, points, _ = self._detector.detectAndDecode(arr)
                if text:
                    out.append({"text": text, "rect": _rect_from_points(points)})
        except Exception:
            pass
        return out


def _rect_from_points(points):
    try:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        return (int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 界面
# ---------------------------------------------------------------------------

PREVIEW_MAX_W = 760
PREVIEW_MAX_H = 560


class ReceiverApp:

    POLL_MS = 50

    def __init__(self, root: tk.Tk):
        self.root = root
        self.core = ReceiverCore(
            outdir=self._default_outdir(),
            log=self.log,
            on_conflict=self._ask_conflict,
            on_change=self._on_core_change,
        )
        self.source = ScreenSource()
        self.decoder = None
        self.region = None                 # None = 整个虚拟桌面
        self.scanning = False
        self._worker = None
        self._stop_flag = threading.Event()
        self.q_preview: queue.Queue = queue.Queue(maxsize=2)
        self.q_text: queue.Queue = queue.Queue()
        # 同一帧文本被解码到 confirm_n 次才认账（按文本累计，避免两帧交替出现时互相饿死）
        self.frame_counts: dict[str, int] = {}
        self.frame_order: list[str] = []
        self.confirm_n = CONFIRM_DEFAULT
        self.fps = FPS_DEFAULT
        self.frames_seen = 0
        self.scan_started_at = 0.0
        self._preview_img = None
        self._preview_scale = 1.0
        self._last_preview_sig = None
        self.last_frame_at = 0.0           # 最近一次扫到有效帧的时刻，用来发现发送端停了

        root.title("二维码传文件 · 接收端（外网）")
        root.geometry("1180x820")
        root.minsize(900, 620)

        try:
            os.makedirs(self.core.outdir, exist_ok=True)
        except OSError:
            pass

        self._build_ui()
        self._poll()
        self.log("就绪。请让内网发送端开始发送，然后点【开始扫描】。", "info")
        self.log("提示：本窗口别挡住二维码；二维码最好有 300 像素以上，越清晰越稳。", "info")
        self._report_pending()

    # -- 界面搭建 -----------------------------------------------------------

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(8, 6, 8, 2))
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="输出目录").pack(side=tk.LEFT)
        self.var_outdir = tk.StringVar(value=self.core.outdir)
        ttk.Entry(top, textvariable=self.var_outdir, width=42).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="选择…", command=self.on_choose_outdir).pack(side=tk.LEFT)
        ttk.Button(top, text="打开目录", command=self.on_open_outdir).pack(side=tk.LEFT, padx=4)

        top2 = ttk.Frame(self.root, padding=(8, 2))
        top2.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top2, text="截屏范围").pack(side=tk.LEFT)
        self.var_monitor = tk.StringVar(value="整个屏幕")
        self.cmb_monitor = ttk.Combobox(top2, textvariable=self.var_monitor, state="readonly",
                                        width=16, values=["整个屏幕"])
        self.cmb_monitor.pack(side=tk.LEFT, padx=4)
        self.cmb_monitor.bind("<<ComboboxSelected>>", self._on_monitor_change)
        ttk.Button(top2, text="框选二维码区域", command=self.on_select_region).pack(side=tk.LEFT)
        ttk.Button(top2, text="用整个屏幕", command=self.on_clear_region).pack(side=tk.LEFT, padx=4)

        ttk.Label(top2, text="   采样帧率").pack(side=tk.LEFT)
        self.var_fps = tk.StringVar(value=str(FPS_DEFAULT))
        ttk.Spinbox(top2, from_=1, to=30, width=4, textvariable=self.var_fps).pack(side=tk.LEFT, padx=4)
        ttk.Label(top2, text="同一帧确认").pack(side=tk.LEFT)
        self.var_confirm = tk.StringVar(value=str(CONFIRM_DEFAULT))
        ttk.Spinbox(top2, from_=1, to=5, width=3, textvariable=self.var_confirm).pack(side=tk.LEFT, padx=4)
        ttk.Label(top2, text="次才认账").pack(side=tk.LEFT)

        self.btn_scan = ttk.Button(top2, text="开始扫描", command=self.on_toggle_scan)
        self.btn_scan.pack(side=tk.LEFT, padx=(16, 4))
        ttk.Button(top2, text="放弃本次会话", command=self.on_discard).pack(side=tk.LEFT, padx=4)
        ttk.Button(top2, text="关闭", command=self.on_close).pack(side=tk.RIGHT)

        body = ttk.Frame(self.root, padding=(8, 4))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(left, text="截屏预览（绿框=识别到的二维码）").pack(side=tk.TOP, anchor="w")
        self.canvas = tk.Canvas(left, bg="#202020", highlightthickness=1,
                                highlightbackground="#888888")
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.var_preview_info = tk.StringVar(value="未开始扫描")
        ttk.Label(left, textvariable=self.var_preview_info, anchor="w").pack(side=tk.TOP, fill=tk.X)

        right = ttk.Frame(body, width=420)
        right.pack(side=tk.LEFT, fill=tk.BOTH, padx=(10, 0))
        right.pack_propagate(False)

        box = ttk.LabelFrame(right, text="本次传输", padding=8)
        box.pack(side=tk.TOP, fill=tk.X)
        self.var_info = tk.StringVar(value="（还没收到起始帧）")
        ttk.Label(box, textvariable=self.var_info, justify=tk.LEFT,
                  anchor="w").pack(side=tk.TOP, fill=tk.X)

        self.var_progress = tk.StringVar(value="")
        ttk.Label(box, textvariable=self.var_progress, anchor="w").pack(side=tk.TOP, fill=tk.X,
                                                                       pady=(6, 2))
        self.bar = ttk.Progressbar(box, mode="determinate", maximum=100)
        self.bar.pack(side=tk.TOP, fill=tk.X)

        self.var_big = tk.StringVar(value="等待开始")
        self.lbl_big = tk.Label(right, textvariable=self.var_big, wraplength=390,
                                justify=tk.LEFT, font=("Microsoft YaHei UI", 15, "bold"),
                                fg="#1a5fb4", anchor="w")
        self.lbl_big.pack(side=tk.TOP, fill=tk.X, pady=10)

        logbox = ttk.LabelFrame(right, text="日志", padding=4)
        logbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.txt = tk.Text(logbox, height=10, wrap="word", state="disabled",
                           font=("Consolas", 9))
        scroll = ttk.Scrollbar(logbox, command=self.txt.yview)
        self.txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.txt.tag_configure("error", foreground="#c01c28")
        self.txt.tag_configure("warn", foreground="#a06000")
        self.txt.tag_configure("ok", foreground="#1a7f37")

    def _default_outdir(self):
        base = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(base):
            base = os.path.expanduser("~")
        return os.path.join(base, "二维码接收")

    # -- 日志 ---------------------------------------------------------------

    def log(self, message: str, level: str = "info"):
        stamp = time.strftime("%H:%M:%S")
        line = "[%s] %s\n" % (stamp, message)
        if getattr(self, "_last_log", None) == message:
            return                          # 同一句话不重复刷屏
        self._last_log = message
        try:
            self.txt.configure(state="normal")
            self.txt.insert("end", line, level if level in ("error", "warn", "ok") else "")
            self.txt.see("end")
            if int(self.txt.index("end-1c").split(".")[0]) > 800:
                self.txt.delete("1.0", "200.0")
            self.txt.configure(state="disabled")
        except tk.TclError:
            pass
        self.var_preview_info.set(message)

    # -- 扫描控制 -----------------------------------------------------------

    def on_toggle_scan(self):
        if self.scanning:
            self.stop_scan()
        else:
            self.start_scan()

    def start_scan(self):
        try:
            self.fps = max(1, min(30, int(self.var_fps.get())))
            self.confirm_n = max(1, min(5, int(self.var_confirm.get())))
        except ValueError:
            messagebox.showerror("参数有误", "采样帧率和连续确认次数要填整数。", parent=self.root)
            return
        try:
            self.source.open()
            if self.decoder is None:
                self.decoder = QrDecoder()
        except Exception as exc:
            messagebox.showerror("无法开始扫描", str(exc), parent=self.root)
            return

        self._refresh_monitor_list()
        self.core.outdir = self.var_outdir.get().strip() or self.core.outdir
        try:
            os.makedirs(self.core.outdir, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("输出目录不可用", "%s\n\n%s" % (self.core.outdir, exc),
                                 parent=self.root)
            return
        if self.region is None:
            self.region = self._region_for_monitor(self.var_monitor.get())

        self._stop_flag.clear()
        self._worker = threading.Thread(target=self._capture_loop, daemon=True)
        self._worker.start()
        self.scanning = True
        self.scan_started_at = time.monotonic()
        self.btn_scan.configure(text="停止扫描")
        self.var_big.set("扫描中…等待起始帧")
        self.log("开始扫描，范围 %s，解码器 %s"
                 % (self._region_desc(), " + ".join(self.decoder.backends)), "ok")
        if "pyzbar" not in self.decoder.backends:
            # 实测 OpenCV 单独用时对较大的二维码识别率很低（干净图像都会失败），
            # 这条警告必须显眼，否则用户会以为是二维码/参数的问题
            self.log("⚠ 没有装 pyzbar，只能用 OpenCV 解码。实测它对大二维码识别率很低，"
                     "请执行：pip install pyzbar", "error")
            self.var_big.set("⚠ 缺 pyzbar\n仅用 OpenCV 解码\n识别率很低\n请 pip install pyzbar")
            self.lbl_big.configure(fg="#c01c28")

    def stop_scan(self):
        self.scanning = False
        self._stop_flag.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        self.source.close()
        self.btn_scan.configure(text="开始扫描")
        self.log("已停止扫描", "info")

    def _refresh_monitor_list(self):
        monitors = self.source.monitors
        values = ["整个屏幕"]
        if len(monitors) > 1:
            for i, m in enumerate(monitors[1:], start=1):
                values.append("显示器 %d（%d×%d）" % (i, m["width"], m["height"]))
        self.cmb_monitor.configure(values=values)
        if self.var_monitor.get() not in values:
            self.var_monitor.set(values[0])

    def _on_monitor_change(self, _event=None):
        self.region = self._region_for_monitor(self.var_monitor.get())
        self.core.outdir = self.var_outdir.get().strip() or self.core.outdir
        self.log("截屏范围改为：%s" % self._region_desc(), "info")

    def _region_for_monitor(self, label: str):
        monitors = self.source.monitors
        if label.startswith("显示器 ") and len(monitors) > 1:
            try:
                idx = int(label.split()[1])
                m = monitors[idx]
                return {"left": m["left"], "top": m["top"],
                        "width": m["width"], "height": m["height"]}
            except (ValueError, IndexError):
                pass
        return dict(self.source.virtual_screen())

    def _region_desc(self):
        if self.region is None:
            return "整个屏幕"
        return "%d,%d 起 %d×%d" % (self.region["left"], self.region["top"],
                                   self.region["width"], self.region["height"])

    def on_clear_region(self):
        self.region = self._region_for_monitor(self.var_monitor.get())
        self.log("截屏范围设为整个屏幕", "info")

    def on_select_region(self):
        """全屏半透明遮罩上拖一个框，框住内网窗口里的二维码。"""
        try:
            self.source.open()
        except Exception as exc:
            messagebox.showerror("无法截屏", str(exc), parent=self.root)
            return
        vs = self.source.virtual_screen()
        overlay = tk.Toplevel(self.root)
        overlay.title("框选二维码区域")
        overlay.attributes("-topmost", True)
        overlay.overrideredirect(True)
        overlay.geometry("%dx%d+%d+%d" % (vs["width"], vs["height"], vs["left"], vs["top"]))
        try:
            overlay.attributes("-alpha", 0.35)
        except tk.TclError:
            pass
        canvas = tk.Canvas(overlay, bg="#101010", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_text(vs["width"] // 2, 40, fill="#ffffff",
                           font=("Microsoft YaHei UI", 16, "bold"),
                           text="按住鼠标左键拖出一个框，把二维码框进去；按 Esc 取消")
        state = {"x0": 0, "y0": 0, "rect": None, "id": None}

        def on_press(event):
            state["x0"], state["y0"] = event.x, event.y
            if state["id"] is not None:
                canvas.delete(state["id"])
            state["id"] = canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                  outline="#00ff66", width=3)

        def on_drag(event):
            if state["id"] is not None:
                canvas.coords(state["id"], state["x0"], state["y0"], event.x, event.y)

        def on_release(event):
            x0, y0 = min(state["x0"], event.x), min(state["y0"], event.y)
            x1, y1 = max(state["x0"], event.x), max(state["y0"], event.y)
            overlay.destroy()
            if x1 - x0 < 60 or y1 - y0 < 60:
                messagebox.showinfo("框太小", "框选区域太小了，请重新框选。", parent=self.root)
                return
            self.region = {"left": vs["left"] + x0, "top": vs["top"] + y0,
                           "width": x1 - x0, "height": y1 - y0}
            self.log("截屏范围已框选为 %s（二维码放在框里，尽量占满）" % self._region_desc(), "ok")

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", lambda _e: overlay.destroy())
        overlay.focus_force()

    # -- 采集线程 -----------------------------------------------------------

    def _capture_loop(self):
        """独立线程：截屏 → 解码 → 丢进队列。界面线程只负责状态机。"""
        period = 1.0 / max(1, self.fps)
        last_sig = None
        last_results = []
        errors = 0
        source = ScreenSource()                 # mss 实例必须在本线程创建
        try:
            source.open()
        except Exception as exc:
            self.q_text.put(("__error__", "截屏初始化失败：%s" % exc))
            return
        try:
            while not self._stop_flag.is_set():
                started = time.monotonic()
                region = self.region or source.virtual_screen()
                try:
                    image, sig = source.grab(region)
                except Exception as exc:
                    errors += 1
                    if errors in (1, 10, 100):
                        self.q_text.put(("__error__", "截屏失败：%s" % exc))
                    time.sleep(0.3)
                    continue
                errors = 0
                if sig == last_sig:
                    results = last_results      # 画面没变，沿用上次的解码结果，省 CPU
                else:
                    try:
                        results = self.decoder.decode(image)
                    except Exception:
                        results = []
                    last_sig, last_results = sig, results
                if results:
                    self.q_text.put(("frames", results))
                self._push_preview(image, results)
                elapsed = time.monotonic() - started
                if elapsed < period:
                    time.sleep(period - elapsed)
        finally:
            source.close()

    def _push_preview(self, image, results):
        try:
            scale = min(PREVIEW_MAX_W / image.width, PREVIEW_MAX_H / image.height, 1.0)
            size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
            thumb = image.resize(size, Image.BILINEAR) if scale < 1.0 else image.copy()
            rects = []
            for item in results:
                if item.get("rect"):
                    x, y, w, h = item["rect"]
                    rects.append((x * scale, y * scale, (x + w) * scale, (y + h) * scale))
            payload = (thumb, rects, scale)
            try:
                self.q_preview.put_nowait(payload)
            except queue.Full:
                try:
                    self.q_preview.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.q_preview.put_nowait(payload)
                except queue.Full:
                    pass
        except Exception:
            pass

    # -- 界面轮询 -----------------------------------------------------------

    def _poll(self):
        try:
            payload = None
            try:
                while True:
                    payload = self.q_preview.get_nowait()
            except queue.Empty:
                pass
            if payload is not None and ImageTk is not None:
                self._show_preview(*payload)

            try:
                while True:
                    kind, data = self.q_text.get_nowait()
                    if kind == "__error__":
                        self.log(data, "error")
                    else:
                        for item in data:
                            self._handle_frame(item)
            except queue.Empty:
                pass

            # 发送端停了 / 二维码被挡住了：给个提示，别让操作员干等
            if self.scanning and self.core.status == STATUS_RECEIVING and self.last_frame_at:
                idle = time.monotonic() - self.last_frame_at
                if idle > STALL_HINT_SECONDS:
                    self.var_big.set("⚠ 已经 %.0f 秒没扫到任何帧\n"
                                     "请检查发送端是否还在发送、\n二维码有没有被窗口挡住"
                                     % idle)
                    self.lbl_big.configure(fg="#a06000")
        finally:
            self.root.after(self.POLL_MS, self._poll)

    def _show_preview(self, thumb, rects, _scale):
        self._preview_img = ImageTk.PhotoImage(thumb)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._preview_img, anchor="nw")
        for x0, y0, x1, y1 in rects:
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#00ff66", width=2)
        self.frames_seen += 1
        if self.scanning and self.frames_seen % 10 == 0:
            elapsed = max(0.001, time.monotonic() - self.scan_started_at)
            self.var_preview_info.set("已采样 %.0f 帧（%.1f 帧/秒）｜ %s"
                                      % (self.frames_seen, self.frames_seen / elapsed,
                                         self._region_desc()))

    def _handle_frame(self, item):
        text = item["text"].strip()
        if parse_frame(text) is None:        # 不是本协议的二维码，直接无视
            self.core.stats["invalid"] += 1
            return
        self.last_frame_at = time.monotonic()
        seen = self.frame_counts.get(text, 0) + 1
        if seen < self.confirm_n:
            self.frame_counts[text] = seen
            return
        self.frame_counts[text] = 0          # 认账后清零；同一帧再出现会重新累计，用于补校验
        if text not in self.frame_order:
            self.frame_order.append(text)
            if len(self.frame_order) > 12:   # 长时间运行也不会把字典撑大
                self.frame_counts.pop(self.frame_order.pop(0), None)
        try:
            result = self.core.feed(text)
        except Exception as exc:
            # 磁盘满、目录被删、权限变化之类的问题不能把界面搞崩，
            # 进度已经落在 .qrtstate 里，修好之后重新扫描即可接着收
            self.log("处理这一帧时出错：%s: %s（修好后重新点【开始扫描】可接着收）"
                     % (type(exc).__name__, exc), "error")
            return
        self._on_result(result)

    def _on_result(self, result: dict):
        status = result.get("status")
        if status == "wrong_session":
            self.var_big.set("⚠ 扫到的是另一次传输的数据帧\n（发送端换了文件，但本机\n没扫到新的起始帧）\n"
                             "请让发送端重新发送起始帧")
            self.lbl_big.configure(fg="#c01c28")
            self.root.bell()
        elif status in ("conflict_blocked", "create_failed"):
            self.var_big.set("⚠ 本次传输无法进行\n请看右侧日志处理")
            self.lbl_big.configure(fg="#c01c28")
        elif status == "gap":
            self.var_big.set("⚠ 缺第 %d 包！\n已停止接收。\n请把发送端【起始序号】\n改成 %d 后点【重发起始帧】"
                             % (result["expected"], result["expected"]))
            self.lbl_big.configure(fg="#c01c28")
            self.root.bell()
        elif status == "incomplete":
            self.var_big.set("⚠ 还缺 %d 包（%s）\n请让发送端从第 %d 包重发"
                             % (self.core.session.total - self.core.session.count,
                                result["missing"], result["expected"]))
            self.lbl_big.configure(fg="#c01c28")
            self.root.bell()
        elif status == "hash_mismatch":
            self.var_big.set("✖ 整文件校验失败！\n已清空本次进度，\n"
                             "请把发送端【起始序号】改回 0\n重新完整传一遍")
            self.lbl_big.configure(fg="#c01c28")
            self.root.bell()
        elif status == "completed":
            self.var_big.set("✔ 传输完成\n%s" % os.path.basename(result["path"]))
            self.lbl_big.configure(fg="#1a7f37")

    def _on_core_change(self):
        info = self.core.progress()
        if info is None:
            self.var_info.set("（还没收到起始帧）")
            self.var_progress.set("")
            self.bar["value"] = 0
            return
        self.var_info.set(
            "文件：%s\n大小：%s　分包：%d 字节 × %d 包\n会话：%s\n已收：%d 包　重复帧：%d　校验错：%d"
            % (info["name"], human_size(info["size"]), info["chunk"], info["total"],
               info["session"], info["received"], self.core.stats["duplicate"],
               self.core.stats["bad_crc"]))
        percent = info["received"] * 100.0 / max(1, info["total"])
        self.var_progress.set("进度 %d / %d 包（%.1f%%）　下一包应为第 %d 包"
                              % (info["received"], info["total"], percent, info["expected"]))
        self.bar["value"] = percent
        if info["status"] == STATUS_RECEIVING and self.core.stats["gap"] == 0:
            self.var_big.set("接收中…等第 %d 包" % info["expected"])
            self.lbl_big.configure(fg="#1a5fb4")

    # -- 其它按钮 -----------------------------------------------------------

    def _ask_conflict(self, info) -> bool:
        return messagebox.askyesno(
            "发现同名文件的旧进度",
            "输出目录里有一个没传完的「%s」，但这次收到的起始帧参数对不上：\n\n"
            "  旧：%s，分包 %d 字节，%d 包\n  新：%s，分包 %d 字节，%d 包\n\n"
            "说明文件内容或分包设置变了。是否丢弃旧进度、重新开始？\n"
            "（选「否」则保留旧进度，但本次会收不下去）"
            % (info["name"], human_size(info["old_size"]), info["old_chunk"], info["old_total"],
               human_size(info["new_size"]), info["new_chunk"], info["new_total"]),
            parent=self.root)

    def _report_pending(self):
        pending = list_pending_sessions(self.core.outdir)
        if not pending:
            return
        for session, _ in pending:
            session.close()
            self.log("输出目录里有未完成的传输：%s（已收 %d/%d 包，等待第 %d 包）——"
                     "发送端一发这个文件就会自动接着收"
                     % (session.file_name, session.count, session.total,
                        session.first_missing(0)), "warn")

    def on_choose_outdir(self):
        path = filedialog.askdirectory(title="选择接收文件的保存目录",
                                       initialdir=self.core.outdir)
        if not path:
            return
        self.var_outdir.set(path)
        self.core.outdir = path
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
        self.log("输出目录改为：%s" % path, "ok")
        self._report_pending()

    def on_open_outdir(self):
        path = self.var_outdir.get().strip()
        if not os.path.isdir(path):
            messagebox.showinfo("目录不存在", "目录还不存在：%s" % path, parent=self.root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)                                  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        except Exception as exc:
            messagebox.showerror("打不开目录", str(exc), parent=self.root)

    def on_discard(self):
        if self.core.session is None:
            # 没有活动会话，但磁盘上可能还留着没传完的进度（比如参数冲突后选了「保留旧进度」，
            # 或者建立接收文件失败）。这是唯一的清理入口，得让它能用。
            pending = list_pending_sessions(self.core.outdir)
            if not pending:
                messagebox.showinfo("没有进行中的传输", "当前还没有收到起始帧。", parent=self.root)
                return
            detail = "\n".join("  · %s（已收 %d/%d 包）"
                               % (s.file_name, s.count, s.total) for s, _ in pending)
            if not messagebox.askyesno(
                    "删除未完成的传输",
                    "当前没有正在接收的传输，但输出目录里还有这些没传完的进度：\n\n%s\n\n"
                    "确定要全部删除吗？删除后必须让发送端从第 0 包重新传。"
                    % detail, parent=self.root):
                return
            for session, _ in pending:
                session.discard()
            self.core.reset()
            self.var_big.set("已清理，等待起始帧")
            self.lbl_big.configure(fg="#1a5fb4")
            self.log("已删除输出目录里未完成的传输进度", "warn")
            return
        name = self.core.session.file_name
        if not messagebox.askyesno(
                "放弃本次会话",
                "确定要丢弃「%s」已收到的 %d 包数据吗？\n丢弃后必须让发送端从第 0 包重新传。"
                % (name, self.core.session.count), parent=self.root):
            return
        self.core.session.discard()
        self.core.reset()
        self.frame_counts.clear()
        self.frame_order.clear()
        self.var_big.set("已放弃，等待起始帧")
        self.lbl_big.configure(fg="#1a5fb4")
        self.log("已放弃会话并删除临时文件", "warn")

    def on_close(self):
        self.stop_scan()
        if self.core.session is not None:
            self.core.session.save_state(force=True)
            self.core.session.close()
        self.root.destroy()


# ---------------------------------------------------------------------------

def enable_dpi_awareness():
    """Windows 高分屏下让 tkinter 坐标 = 物理像素，否则框选区域会和实际截屏错位。"""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # Windows 8.1+
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()     # 更老的 Windows
        except Exception:
            pass                                          # 非 Windows 平台，忽略


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    app = ReceiverApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
