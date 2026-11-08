#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sender_windows.py —— 二维码单向传文件 · 发送端（在内网/隔离网的 Windows 上运行）

用途
    把一个文件切成若干块，每块打成一个二维码，按固定节奏在屏幕上轮播。
    对端（外网机器）用 receiver_windows.py 截屏解码，最后还原出原文件。
    数据只能从内网流向外部，没有任何反向通道。

依赖
    Python 3.8+（Windows 官方安装包自带 tkinter）
    pip install qrcode          # 纯 Python；二维码直接用 tkinter Canvas 画，不需要 Pillow

运行
    python sender_windows.py

协议（必须与 receiver_windows.py 完全一致，改动时两边同步改）
    所有帧都是 ASCII 文本，字段用 '|' 分隔，二进制内容一律 base64。
    起始帧  QRT1|S|<会话号>|<起始序号>|<总包数>|<分包字节>|<文件字节>|<b64(文件名)>|<crc32>
    数据帧  QRT1|D|<会话号>|<序号>|<crc32:8位小写hex>|<b64(分片数据)>
            crc32 = zlib.crc32(b"<会话号>|<序号>|<b64数据>")，覆盖会话号、序号和数据本身
    结束帧  QRT1|E|<总包数>|<文件字节>|<sha256>|<b64(文件名)>|<crc32>

    三种帧都带校验码：数据帧的 crc32 在中间、护着序号和数据；起始帧/结束帧的 crc32 在
    最后，覆盖它前面的整串内容。这样某一帧万一被解错，接收端只会「忽略这一帧、继续等」，
    而不会拿着错参数建出一个错误的会话，或者把好数据误判成校验失败。

    序号从 0 开始，共 <总包数> 个，最后一包可能不足 <分包字节>。
    会话号 = sha256(文件内容) 的前 16 位十六进制：同一个文件重复发送时会话号相同，
    对端据此认出「这是同一个文件的续传」而不是新文件。
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
import sys
import threading
import time
import tkinter as tk
import zlib
from tkinter import filedialog, messagebox, ttk

try:
    import qrcode
    from qrcode.exceptions import DataOverflowError
    from qrcode.util import MODE_8BIT_BYTE, QRData
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "缺少依赖 qrcode，请先在命令行执行：\n\n    pip install qrcode\n\n"
    )
    raise

# ---------------------------------------------------------------------------
# 协议定义（必须与 receiver_windows.py 保持一致）
# ---------------------------------------------------------------------------

PROTO_VERSION = "QRT1"
FRAME_START = "S"
FRAME_DATA = "D"
FRAME_END = "E"

# 二维码静区（四周留白的模块数）。QR 规范要求至少 4，不能省，否则扫不出来。
QR_QUIET_ZONE = 4

# 数据帧头部在最坏情况下的字符数：`QRT1|D|<16位会话号>|<6位序号>|<8位crc>|`
DATA_HEADER_MAX = len("QRT1|D|") + 16 + 1 + 6 + 1 + 8 + 1

# 内容超出二维码容量时，qrcode 视情况抛这两种异常之一（版本固定时抛前者，
# 自动选版本时内部会把版本算到 41 而抛 ValueError），统一按「装不下」处理。
QR_TOO_BIG = (DataOverflowError, ValueError)

ECC_LEVELS = {
    "L（约 7% 容错，装得最多）": qrcode.constants.ERROR_CORRECT_L,
    "M（约 15% 容错，推荐）": qrcode.constants.ERROR_CORRECT_M,
    "Q（约 25% 容错，更耐压缩失真）": qrcode.constants.ERROR_CORRECT_Q,
    "H（约 30% 容错，装得最少）": qrcode.constants.ERROR_CORRECT_H,
}
ECC_DEFAULT = "M（约 15% 容错，推荐）"

# 二维码最大版本（40）在字节模式下的容量（字符数），QR 标准值。
V40_CAPACITY = {
    qrcode.constants.ERROR_CORRECT_L: 2953,
    qrcode.constants.ERROR_CORRECT_M: 2331,
    qrcode.constants.ERROR_CORRECT_Q: 1663,
    qrcode.constants.ERROR_CORRECT_H: 1273,
}


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text)


def _append_crc(fields) -> str:
    """把字段拼起来，在末尾追加一个覆盖整串内容的 crc32。"""
    body = "|".join(fields)
    return "%s|%08x" % (body, zlib.crc32(body.encode("ascii")) & 0xFFFFFFFF)


def build_start_frame(session: str, start_index: int, total: int,
                      chunk_size: int, file_size: int, file_name: str) -> str:
    return _append_crc([
        PROTO_VERSION, FRAME_START, session, str(start_index), str(total),
        str(chunk_size), str(file_size), b64e(file_name.encode("utf-8")),
    ])


def build_data_frame(session: str, index: int, payload: bytes) -> str:
    """数据帧也带会话号：否则换文件后如果起始帧没扫到，新文件的数据会被
    按偏移写进旧文件没传完的会话里，最后整文件校验还能通过（字节是自洽的），
    结果就是「用旧文件名存下新文件内容」这种静默错误交付。"""
    body = b64e(payload)
    crc = zlib.crc32(("%s|%d|%s" % (session, index, body)).encode("ascii")) & 0xFFFFFFFF
    return "|".join([PROTO_VERSION, FRAME_DATA, session, str(index), "%08x" % crc, body])


def build_end_frame(total: int, file_size: int, sha256_hex: str, file_name: str) -> str:
    return _append_crc([
        PROTO_VERSION, FRAME_END, str(total), str(file_size), sha256_hex,
        b64e(file_name.encode("utf-8")),
    ])


# ---------------------------------------------------------------------------
# 传输模型（不依赖 tkinter，便于在无界面环境下测试）
# ---------------------------------------------------------------------------

class Transfer:
    """一次发送任务：文件 → 分片 → 各帧文本。"""

    def __init__(self, path: str, chunk_size: int, ecc_label: str = ECC_DEFAULT):
        self.path = path
        self.file_name = os.path.basename(path)
        with open(path, "rb") as fp:
            self.data = fp.read()
        self.file_size = len(self.data)
        self.sha256_hex = hashlib.sha256(self.data).hexdigest()
        self.session = self.sha256_hex[:16]
        self.chunk_size = int(chunk_size)
        if self.chunk_size <= 0:
            raise ValueError("分包大小必须是正整数")
        # 空文件也当成 1 包（内容为空），保证流程一致
        self.total = max(1, math.ceil(self.file_size / self.chunk_size)) if self.file_size else 1
        self.ecc_label = ecc_label
        self.ecc = ECC_LEVELS[ecc_label]
        self._matrix_cache: dict[str, tuple] = {}
        self._cache_lock = threading.Lock()

    # -- 分片 ---------------------------------------------------------------

    def payload(self, index: int) -> bytes:
        """取第 index 包的数据；最后一包可以短于 chunk_size。"""
        if not (0 <= index < self.total):
            raise IndexError("包序号越界: %d" % index)
        start = index * self.chunk_size
        return self.data[start:start + self.chunk_size]

    def frame(self, index: int) -> str:
        return build_data_frame(self.session, index, self.payload(index))

    def start_frame(self, start_index: int) -> str:
        return build_start_frame(self.session, start_index, self.total,
                                 self.chunk_size, self.file_size, self.file_name)

    def end_frame(self) -> str:
        return build_end_frame(self.total, self.file_size, self.sha256_hex, self.file_name)

    # -- 二维码 -------------------------------------------------------------

    def matrix(self, text: str):
        """文本 → 二维码模块矩阵（不含静区）。带缓存，避免重复计算。

        纯 Python 生成一个大二维码要 0.2 秒以上（v27 约 0.25 秒），所以主线程切换帧时
        绝不能现算——发送端会在后台线程里提前把后面几帧算好（见 SenderApp._prefetch）。
        这个缓存会被主线程和预生成线程同时访问，因此加锁。
        """
        with self._cache_lock:
            cached = self._matrix_cache.get(text)
        if cached is not None:
            return cached
        qr = qrcode.QRCode(error_correction=self.ecc, box_size=1, border=0)
        qr.add_data(QRData(text, mode=MODE_8BIT_BYTE))  # 强制字节模式，兼容性最好
        qr.make(fit=True)
        result = (qr.get_matrix(), qr.version)
        with self._cache_lock:
            if len(self._matrix_cache) > 64:
                self._matrix_cache.clear()
            self._matrix_cache[text] = result
        return result

    def has_matrix(self, text: str) -> bool:
        with self._cache_lock:
            return text in self._matrix_cache

    @staticmethod
    def fits(text: str, ecc) -> bool:
        try:
            qr = qrcode.QRCode(error_correction=ecc, box_size=1, border=0)
            qr.add_data(QRData(text, mode=MODE_8BIT_BYTE))
            qr.make(fit=True)
            return True
        except QR_TOO_BIG:
            return False

    @classmethod
    def max_chunk_size(cls, ecc_label: str) -> int:
        """当前纠错级别下，一个二维码最多能装多少字节的分片数据。

        二维码最大版本（40）在字节模式下的容量是标准值（见 V40_CAPACITY）。
        数据要先 base64（4 个字符装 3 字节），帧头按最坏情况算：
        `QRT1|D|<16位会话号>|999999|xxxxxxxx|` 共 39 个字符，序号 6 位十进制足够 100 万包。
        所以 4*ceil(n/3) + 39 <= 容量。算完再真的编码一次验证，防止库的版本差异。
        """
        ecc = ECC_LEVELS[ecc_label]
        capacity = V40_CAPACITY[ecc]
        size = max(1, ((capacity - DATA_HEADER_MAX) // 4) * 3)
        probe_session = "0" * 16
        while size > 1 and not cls.fits(build_data_frame(probe_session, 999999, b"\x00" * size), ecc):
            size -= 1
        return size


# ---------------------------------------------------------------------------
# 界面
# ---------------------------------------------------------------------------

PHASE_IDLE = "idle"
PHASE_START = "start"
PHASE_DATA = "data"
PHASE_END = "end"


def human_size(n: int) -> str:
    for unit, base in (("B", 1), ("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3)):
        if n < base * 1024 or unit == "GB":
            return "%.1f %s" % (n / base, unit) if base > 1 else "%d B" % n
    return "%d B" % n


def human_time(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return "%d 秒" % seconds
    if seconds < 3600:
        return "%d 分 %02d 秒" % (seconds // 60, seconds % 60)
    return "%d 小时 %02d 分" % (seconds // 3600, (seconds % 3600) // 60)


class SenderApp:

    TICK_MS = 100          # 界面刷新间隔

    def __init__(self, root: tk.Tk):
        self.root = root
        self.transfer: Transfer | None = None
        self.phase = PHASE_IDLE
        self.index = 0                 # 当前显示的包序号
        self.paused = False
        self.next_flip_at = 0.0        # 下一包切换时刻
        self.start_deadline = 0.0      # 起始帧结束时刻
        self.shown_text = None         # 当前画面上这一帧的文本
        self.shown_scale = 0
        self.shown_version = 0
        self.shown_modules = 0
        self.started_at = 0.0          # 本次发送开始时刻（含起始帧）
        self.data_started_at = 0.0     # 进入数据阶段的时刻，用来算速率
        self.start_index = 0           # 本次发送的起始包序号
        self.interval = 0.4
        self.hold_seconds = 10.0
        self._pause_at = 0.0
        self._last_size = (0, 0)
        self._resize_job = None
        self._tick_job = None
        self._prefetching: set[str] = set()
        self._max_chunk_cache: dict[str, int] = {}
        self._capacity_hint = ""

        root.title("二维码传文件 · 发送端（内网）")
        root.geometry("1020x920")
        root.minsize(600, 520)
        try:
            root.state("zoomed")       # Windows 下最大化
        except tk.TclError:
            pass

        self._build_ui()
        self._bind_keys()
        self._tick()

    # -- 界面搭建 -----------------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 4, "pady": 3}

        # 第一行：文件
        row1 = ttk.Frame(self.root, padding=(8, 6, 8, 0))
        row1.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(row1, text="文件：").pack(side=tk.LEFT)
        self.var_file = tk.StringVar(value="（尚未选择）")
        ttk.Entry(row1, textvariable=self.var_file, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(row1, text="选择文件…", command=self.on_choose_file).pack(side=tk.LEFT)
        self.var_filesize = tk.StringVar(value="")
        ttk.Label(row1, textvariable=self.var_filesize, width=12).pack(side=tk.LEFT, padx=(6, 0))

        # 第二行：参数
        row2 = ttk.Frame(self.root, padding=(8, 4))
        row2.pack(side=tk.TOP, fill=tk.X)
        self.var_chunk = tk.StringVar(value="800")
        self.var_start = tk.StringVar(value="0")
        self.var_interval = tk.StringVar(value="0.4")
        self.var_hold = tk.StringVar(value="10")
        self.var_ecc = tk.StringVar(value=ECC_DEFAULT)

        ttk.Label(row2, text="分包大小(字节)").pack(side=tk.LEFT)
        ttk.Spinbox(row2, from_=50, to=2000, increment=50, width=7,
                    textvariable=self.var_chunk).pack(side=tk.LEFT, **pad)
        ttk.Label(row2, text="起始序号").pack(side=tk.LEFT)
        ttk.Spinbox(row2, from_=0, to=999999, increment=1, width=8,
                    textvariable=self.var_start).pack(side=tk.LEFT, **pad)
        ttk.Label(row2, text="帧间隔(秒)").pack(side=tk.LEFT)
        ttk.Spinbox(row2, from_=0.2, to=30.0, increment=0.1, width=6,
                    textvariable=self.var_interval).pack(side=tk.LEFT, **pad)
        ttk.Label(row2, text="纠错级别").pack(side=tk.LEFT)
        ttk.Combobox(row2, values=list(ECC_LEVELS), textvariable=self.var_ecc,
                     state="readonly", width=26).pack(side=tk.LEFT, **pad)
        self.var_ecc.trace_add("write", lambda *_: self.refresh_capacity_hint())

        # 第三行：按钮
        row3 = ttk.Frame(self.root, padding=(8, 0, 8, 4))
        row3.pack(side=tk.TOP, fill=tk.X)
        self.btn_run = ttk.Button(row3, text="开始发送", command=self.on_run_pause)
        self.btn_run.pack(side=tk.LEFT)
        ttk.Button(row3, text="◀ 上一包", command=lambda: self.step(-1)).pack(side=tk.LEFT, padx=4)
        ttk.Button(row3, text="下一包 ▶", command=lambda: self.step(1)).pack(side=tk.LEFT)
        ttk.Button(row3, text="重发起始帧", command=self.on_resend_start).pack(side=tk.LEFT, padx=(12, 4))
        ttk.Button(row3, text="全屏 (F11)", command=self.toggle_fullscreen).pack(side=tk.LEFT)
        ttk.Button(row3, text="关闭", command=self.on_close).pack(side=tk.RIGHT)

        # 底部：状态栏（先 pack 底部，剩下的空间都给二维码）
        bar = ttk.Frame(self.root, padding=(8, 4))
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.var_status = tk.StringVar(value="就绪：请选择要发送的文件。")
        ttk.Label(bar, textvariable=self.var_status, anchor="w").pack(side=tk.TOP, fill=tk.X)
        self.var_sub = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.var_sub, anchor="w",
                  foreground="#555555").pack(side=tk.TOP, fill=tk.X)

        hint = ttk.Frame(self.root, padding=(8, 2, 8, 6))
        hint.pack(side=tk.BOTTOM, fill=tk.X)
        self.var_hint = tk.StringVar(value=self._default_hint())
        ttk.Label(hint, textvariable=self.var_hint, anchor="w",
                  foreground="#8a4b00", wraplength=980,
                  justify=tk.LEFT).pack(side=tk.TOP, fill=tk.X)

        # 中间：二维码画布
        self.canvas = tk.Canvas(self.root, bg="#ffffff", highlightthickness=0)
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self.refresh_capacity_hint()

    def _default_hint(self) -> str:
        return ("操作提示：对端扫到起始帧后会等你；若对端提示「缺包 N，已停止接收」，"
                "把上面的【起始序号】改成 N，再点【重发起始帧】即可从第 N 包接着传，前面的包不用重发。")

    def _bind_keys(self):
        self.root.bind("<F11>", lambda _e: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda _e: self.toggle_fullscreen(False))
        self.root.bind("<space>", self._on_space)
        self.root.bind("<Left>", lambda _e: self._key_step(-1))
        self.root.bind("<Right>", lambda _e: self._key_step(1))

    def _key_step(self, delta: int):
        # 焦点在输入框里时，方向键留给输入框自己用
        if isinstance(self.root.focus_get(), (ttk.Entry, ttk.Spinbox, tk.Entry)):
            return
        self.step(delta)

    def _on_space(self, _event):
        if isinstance(self.root.focus_get(), (ttk.Entry, ttk.Spinbox, tk.Entry)):
            return "break"
        self.on_run_pause()
        return "break"

    def toggle_fullscreen(self, value: bool | None = None):
        current = bool(self.root.attributes("-fullscreen"))
        self.root.attributes("-fullscreen", (not current) if value is None else value)

    # -- 参数与文件 ---------------------------------------------------------

    def _read_config(self) -> dict:
        def as_int(var, name, lo, hi):
            try:
                value = int(str(var.get()).strip())
            except ValueError:
                raise ValueError("【%s】要填整数" % name)
            if not (lo <= value <= hi):
                raise ValueError("【%s】应在 %d ~ %d 之间" % (name, lo, hi))
            return value

        def as_float(var, name, lo, hi):
            try:
                value = float(str(var.get()).strip())
            except ValueError:
                raise ValueError("【%s】要填数字" % name)
            if not (lo <= value <= hi):
                raise ValueError("【%s】应在 %s ~ %s 之间" % (name, lo, hi))
            return value

        return {
            "chunk": as_int(self.var_chunk, "分包大小", 1, 3000),
            "start": as_int(self.var_start, "起始序号", 0, 10 ** 7),
            # 下限 0.2 秒：接收端默认要求同一帧被独立解出 2 次才认账，
            # 翻页太快它会来不及解第二遍，表现为不停缺包
            "interval": as_float(self.var_interval, "帧间隔", 0.2, 600),
            "hold": as_float(self.var_hold, "起始帧停留", 1, 600),
            "ecc": self.var_ecc.get(),
        }

    def _max_chunk(self, ecc_label: str) -> int:
        """当前纠错级别下二维码最多能装多少字节的分片（结果缓存）。"""
        if ecc_label not in self._max_chunk_cache:
            self._max_chunk_cache[ecc_label] = Transfer.max_chunk_size(ecc_label)
        return self._max_chunk_cache[ecc_label]

    def refresh_capacity_hint(self):
        """把当前纠错级别能装的最大分片字节数显示出来，避免用户填爆。"""
        label = self.var_ecc.get()
        if label not in ECC_LEVELS:
            return
        self._capacity_hint = "当前纠错级别下单包最大约 %d 字节" % self._max_chunk(label)

    def on_choose_file(self):
        if self.phase != PHASE_IDLE and not messagebox.askyesno(
                "正在传输中",
                "现在正在发送，换文件会中断当前这次传输（接收端会停在半路）。\n\n确定要换吗？",
                parent=self.root):
            return
        path = filedialog.askopenfilename(title="选择要发送的文件")
        if not path:
            return
        try:
            cfg = self._read_config()
        except ValueError as exc:
            messagebox.showerror("参数有误", str(exc), parent=self.root)
            return
        try:
            transfer = Transfer(path, cfg["chunk"], cfg["ecc"])
        except Exception as exc:
            messagebox.showerror("无法读取文件", "%s\n\n%s" % (path, exc), parent=self.root)
            return
        self.transfer = transfer
        self.var_file.set(path)
        self.var_filesize.set(human_size(transfer.file_size))
        self.var_start.set("0")
        self.phase = PHASE_IDLE
        self.index = 0
        self.paused = False
        self.shown_text = None
        self.btn_run.configure(text="开始发送")     # 别让按钮停在「暂停」上误导操作员
        self.canvas.delete("all")
        self._set_status(
            "已选择：%s（%s，%d 包 × %d 字节）" % (
                transfer.file_name, human_size(transfer.file_size),
                transfer.total, transfer.chunk_size))
        self._set_sub("SHA-256 %s…  会话号 %s" % (transfer.sha256_hex[:16], transfer.session))
        self.var_hint.set(self._default_hint())

    # -- 状态栏 -------------------------------------------------------------

    def _set_status(self, text: str):
        self.var_status.set(text)

    def _set_sub(self, text: str):
        self.var_sub.set(text)

    # -- 主循环 -------------------------------------------------------------

    def on_run_pause(self):
        if self.transfer is None:
            messagebox.showinfo("还没有选文件", "请先点【选择文件…】。", parent=self.root)
            return
        if self.phase == PHASE_IDLE:
            self.begin()
        else:
            self.paused = not self.paused
            if not self.paused:
                now = time.monotonic()
                if self.phase == PHASE_START:
                    self.start_deadline = now + max(1.0, self.start_deadline - self._pause_at)
                else:
                    self.next_flip_at = now + max(0.05, self.next_flip_at - self._pause_at)
            else:
                self._pause_at = time.monotonic()
            self.btn_run.configure(text="继续" if self.paused else "暂停")
            self._render_status()

    def begin(self, start_index: int | None = None):
        """从 start_index 包开始：先播起始帧，再逐包发送。"""
        assert self.transfer is not None
        try:
            cfg = self._read_config()
        except ValueError as exc:
            messagebox.showerror("参数有误", str(exc), parent=self.root)
            return
        if cfg["chunk"] != self.transfer.chunk_size:
            # 改了分包大小就要重新切片，否则包边界对不上
            try:
                self.transfer = Transfer(self.transfer.path, cfg["chunk"], cfg["ecc"])
            except Exception as exc:
                messagebox.showerror("无法重新分片", str(exc), parent=self.root)
                return
        elif self.transfer.ecc_label != cfg["ecc"]:
            self.transfer = Transfer(self.transfer.path, cfg["chunk"], cfg["ecc"])
            self.transfer._matrix_cache.clear()

        index = cfg["start"] if start_index is None else start_index
        if index >= self.transfer.total:
            messagebox.showerror(
                "起始序号越界",
                "总共只有 %d 包（序号 0 ~ %d），起始序号不能是 %d。"
                % (self.transfer.total, self.transfer.total - 1, index),
                parent=self.root)
            return

        # 先确认这个分包大小二维码装得下（数据帧比起始帧大得多，必须提前拦）
        max_chunk = self._max_chunk(cfg["ecc"])
        if self.transfer.chunk_size > max_chunk:
            messagebox.showerror(
                "分包太大",
                "【分包大小】%d 字节超过了二维码容量：在 %s 下每包最多 %d 字节。\n\n"
                "请把分包大小调到 %d 以内。"
                % (self.transfer.chunk_size, cfg["ecc"].split("（")[0], max_chunk, max_chunk),
                parent=self.root)
            return

        # 总包数太多时序号位数会变长，最后一包那一帧未必还装得下（max_chunk 是按 6 位序号估的）
        if not Transfer.fits(self.transfer.frame(self.transfer.total - 1), self.transfer.ecc):
            messagebox.showerror(
                "包数太多",
                "总包数 %d 太多：序号位数变长之后，最后一包的二维码装不下了。\n\n"
                "请把【分包大小】调大（包数就少了），或者换个小一点的文件。"
                % self.transfer.total, parent=self.root)
            return

        # 起始帧也必须能编码出来
        text = self.transfer.start_frame(index)
        try:
            self.transfer.matrix(text)
        except QR_TOO_BIG:
            messagebox.showerror(
                "起始帧装不下",
                "起始帧（含文件名）装不进二维码，请把文件名改短或把分包大小调小。",
                parent=self.root)
            return

        self.index = index
        self.start_index = index
        self.phase = PHASE_START
        self.paused = False
        now = time.monotonic()
        self.started_at = now
        self.data_started_at = now
        self.start_deadline = now + cfg["hold"]
        self.hold_seconds = cfg["hold"]
        self.interval = cfg["interval"]
        self.next_flip_at = self.start_deadline
        self.btn_run.configure(text="暂停")
        self.shown_text = None
        self.show_text(text)
        self._prefetch_upcoming()          # 起始帧停留期间把第一包先算好
        self._render_status()

    def on_resend_start(self):
        """按当前【起始序号】重播起始帧——缺包续传就靠这个。"""
        if self.transfer is None:
            messagebox.showinfo("还没有选文件", "请先点【选择文件…】。", parent=self.root)
            return
        try:
            cfg = self._read_config()
        except ValueError as exc:
            messagebox.showerror("参数有误", str(exc), parent=self.root)
            return
        self.begin(start_index=cfg["start"])

    def step(self, delta: int):
        if self.transfer is None or self.phase == PHASE_IDLE:
            return
        if self.phase == PHASE_END and delta > 0:
            return                      # 已经是最后一包，结束帧往后没有内容
        target = min(max(self.index + delta, 0), self.transfer.total - 1)
        if self.phase in (PHASE_END, PHASE_START):
            self.phase = PHASE_DATA
            self.data_started_at = time.monotonic()
        self.index = target
        self.show_text(self.transfer.frame(target))
        self.next_flip_at = time.monotonic() + self.interval
        self.paused = False
        self.btn_run.configure(text="暂停")
        self._prefetch_upcoming()
        self._render_status()

    def _tick(self):
        """100ms 一次的心跳：负责倒计时、自动切包、刷新状态。"""
        try:
            now = time.monotonic()
            if self.transfer is not None and not self.paused:
                if self.phase == PHASE_START and now >= self.start_deadline:
                    self.phase = PHASE_DATA
                    self.data_started_at = now
                    self.index = min(self.index, self.transfer.total - 1)
                    self.show_text(self.transfer.frame(self.index))
                    # 计时从「画完」开始算，保证这一帧在屏幕上待满一个 interval
                    self.next_flip_at = time.monotonic() + self.interval
                elif self.phase == PHASE_DATA and now >= self.next_flip_at:
                    if self.index + 1 >= self.transfer.total:
                        self.phase = PHASE_END
                        self.show_text(self.transfer.end_frame())
                    else:
                        self.index += 1
                        self.show_text(self.transfer.frame(self.index))
                        self.next_flip_at = time.monotonic() + self.interval
            self._prefetch_upcoming()
            self._render_status()
        finally:
            self._tick_job = self.root.after(self.TICK_MS, self._tick)

    # -- 后台预生成二维码 ---------------------------------------------------

    def _prefetch(self, text: str | None):
        """在后台线程里把某一帧的二维码算好放进缓存，别卡住界面。"""
        if text is None or self.transfer is None:
            return
        if self.transfer.has_matrix(text) or text in self._prefetching:
            return
        self._prefetching.add(text)

        def work():
            try:
                self.transfer.matrix(text)
            except Exception:
                pass                      # 装不下之类的错误留给主线程按正常路径报
            finally:
                self._prefetching.discard(text)

        threading.Thread(target=work, daemon=True).start()

    def _prefetch_upcoming(self):
        """提前算好接下来要显示的几帧（纯 Python 生成大二维码要 0.2 秒以上）。"""
        t = self.transfer
        if t is None or self.phase == PHASE_IDLE:
            return
        if self.phase == PHASE_START:
            self._prefetch(t.frame(self.index))
        elif self.phase == PHASE_DATA:
            for ahead in (1, 2):
                if self.index + ahead < t.total:
                    self._prefetch(t.frame(self.index + ahead))
            if self.index + 1 >= t.total:
                self._prefetch(t.end_frame())

    # -- 渲染 ---------------------------------------------------------------

    def show_text(self, text: str):
        self.shown_text = text
        self._draw(force=True)

    def _on_canvas_resize(self, _event=None):
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(150, lambda: self._draw(force=True))

    def _draw(self, force: bool = False):
        text = self.shown_text
        if not text or self.transfer is None:
            return
        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        if not force and self.shown_scale and self._last_size == (width, height):
            return
        self._last_size = (width, height)

        try:
            matrix, version = self.transfer.matrix(text)
        except QR_TOO_BIG:
            # 理论上进不来（begin 已校验），兜底避免整条定时器被打断
            self.canvas.delete("all")
            self.var_hint.set("⚠ 当前帧装不进二维码，请把【分包大小】调小后重新开始。")
            return
        n = len(matrix) + 2 * QR_QUIET_ZONE
        scale = max(1, min(width // n, height // n))
        size = n * scale
        x0 = (width - size) // 2
        y0 = (height - size) // 2

        self.canvas.delete("all")
        self.canvas.create_rectangle(x0, y0, x0 + size, y0 + size,
                                     fill="#ffffff", outline="")
        # 按「连续黑模块」合并成矩形，比一格一个矩形快得多
        for row_idx, row in enumerate(matrix):
            col = 0
            row_len = len(row)
            while col < row_len:
                if row[col]:
                    start = col
                    while col < row_len and row[col]:
                        col += 1
                    self.canvas.create_rectangle(
                        x0 + (start + QR_QUIET_ZONE) * scale,
                        y0 + (row_idx + QR_QUIET_ZONE) * scale,
                        x0 + (col + QR_QUIET_ZONE) * scale,
                        y0 + (row_idx + QR_QUIET_ZONE + 1) * scale,
                        fill="#000000", outline="")
                else:
                    col += 1
        self.shown_scale = scale
        self.shown_version = version
        self.shown_modules = n

    def _render_status(self):
        if self.transfer is None:
            return
        t = self.transfer
        if self.phase == PHASE_IDLE:
            return
        if self.phase == PHASE_START:
            left = max(0.0, self.start_deadline - time.monotonic()) if not self.paused else \
                max(0.0, self.start_deadline - self._pause_at)
            self._set_status(
                "① 起始帧（请让对端先扫这一帧）—— %s后开始传数据" % human_time(left))
            self._set_sub("文件 %s ｜ 会话号 %s ｜ 从第 %d 包开始，共 %d 包"
                          % (t.file_name, t.session, self.index, t.total))
        elif self.phase == PHASE_DATA:
            done = self.index + 1                      # 本次已发（含正在显示的这包）
            sent = max(1, self.index - self.start_index + 1)
            ratio = done / t.total
            now = self._pause_at if self.paused else time.monotonic()
            elapsed = max(0.001, now - self.data_started_at)
            speed = sent / elapsed
            remain = (t.total - done) / speed if speed > 0 else 0
            self._set_status(
                "② 传输中：第 %d / %d 包（%.1f%%）%s"
                % (self.index, t.total - 1, ratio * 100, "　【已暂停】" if self.paused else ""))
            self._set_sub(
                "本次已发 %d 包 ｜ 速率 %.1f 包/秒 ｜ 已用 %s ｜ 预计剩余 %s ｜ "
                "本帧 %d 字符 ｜ QR v%d（%d×%d 模块）｜ %d 像素/模块"
                % (sent, speed, human_time(elapsed), human_time(remain),
                   len(self.shown_text or ""), self.shown_version, self.shown_modules,
                   self.shown_modules, self.shown_scale))
            if self.shown_scale < 4:
                self.var_hint.set("⚠ 二维码只有 %d 像素/模块，偏小，对端可能扫不到。"
                                  "建议最大化窗口或按 F11 全屏。" % self.shown_scale)
        elif self.phase == PHASE_END:
            self._set_status("③ 结束帧（保持显示，等对端校验并保存文件）")
            self._set_sub("共 %d 包 ｜ 整文件 SHA-256 %s… ｜ 对端校验通过后即可关闭本窗口"
                          % (t.total, t.sha256_hex[:16]))

    # -- 退出 ---------------------------------------------------------------

    def on_close(self):
        if self._tick_job is not None:
            try:
                self.root.after_cancel(self._tick_job)
            except tk.TclError:
                pass
            self._tick_job = None
        self.root.destroy()


def enable_dpi_awareness():
    """Windows 高分屏下让 tkinter 坐标与物理像素一致，避免界面发虚。"""
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
    app = SenderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
