#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest_gui.py —— 双进程界面联调验收（发送端界面 + 接收端界面，真截屏真解码）

`selftest.py` 里的端到端测试只用了发送端界面，接收端是直接调状态机的；
这个脚本把**两个界面都真的跑起来**，一个进程开发送端、一个进程开接收端，
接收端对屏幕截屏解码，走完整的界面流程，最后比对文件字节。

跑法（Linux 无显示器时用 xvfb-run，屏幕要够宽以放下两个窗口）：

    xvfb-run -a --server-args="-screen 0 2200x1200x24" python3 selftest_gui.py

Windows 上也可以直接跑（会真的弹出两个窗口，能亲眼看到整个过程）：

    python selftest_gui.py

正常结束会打印 "通过"，退出码 0。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SENDER_GEOMETRY = "1020x920+0+0"
RECEIVER_GEOMETRY = "1080x820+1100+0"


def _patch_dialogs():
    """自动化测试里绝不能让模态对话框把流程卡死。"""
    import tkinter.messagebox as mb

    def boom(kind):
        def handler(title="", message="", **_kw):
            print("意外弹窗 %s: %s / %s" % (kind, title, message), flush=True)
            raise SystemExit(3)
        return handler

    mb.showerror = boom("showerror")
    mb.showinfo = boom("showinfo")
    mb.showwarning = boom("showwarning")
    mb.askyesno = lambda title="", message="", **_kw: True


def run_sender(path: str, chunk: int, interval: float, hold: float, timeout: float):
    import tkinter as tk
    import sender_windows as S

    _patch_dialogs()
    root = tk.Tk()
    app = S.SenderApp(root)
    root.geometry(SENDER_GEOMETRY)
    app.transfer = S.Transfer(path, chunk)
    app.var_file.set(path)
    app.var_chunk.set(str(chunk))
    app.var_interval.set(str(interval))
    app.var_hold.set(str(hold))
    app.var_start.set("0")
    root.update()
    root.after(800, app.begin)
    root.after(int(timeout * 1000), root.destroy)
    print("发送端就绪：%s（%d 包）" % (os.path.basename(path), app.transfer.total), flush=True)
    root.mainloop()
    print("发送端退出", flush=True)


def run_receiver(outdir: str, region: dict, timeout: float):
    import tkinter as tk
    import receiver_windows as R

    _patch_dialogs()
    root = tk.Tk()
    app = R.ReceiverApp(root)
    root.geometry(RECEIVER_GEOMETRY)
    app.var_outdir.set(outdir)
    app.core.outdir = outdir
    app.region = dict(region)
    app.var_fps.set("10")
    root.update()

    started = time.monotonic()
    result = {"code": 2}

    def watch():
        if app.core.status == R.STATUS_DONE:
            result["code"] = 0
            result["path"] = app.core.saved_path
            print("接收端完成：%s" % app.core.saved_path, flush=True)
            root.destroy()
            return
        if time.monotonic() - started > timeout:
            result["code"] = 2
            print("接收端超时：状态 %s，已收 %s"
                  % (app.core.status,
                     app.core.session.count if app.core.session else 0), flush=True)
            root.destroy()
            return
        root.after(200, watch)

    root.after(1200, app.start_scan)
    root.after(1500, watch)
    root.mainloop()
    print("接收端退出 code=%d" % result["code"], flush=True)
    sys.exit(result["code"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["sender", "receiver", "both"], default="both")
    parser.add_argument("--file")
    parser.add_argument("--outdir")
    parser.add_argument("--chunk", type=int, default=300)
    parser.add_argument("--interval", type=float, default=0.4)
    parser.add_argument("--hold", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--region", default="0,0,1020,920")
    args = parser.parse_args()

    if args.role == "sender":
        run_sender(args.file, args.chunk, args.interval, args.hold, args.timeout)
        return 0
    if args.role == "receiver":
        left, top, width, height = (int(v) for v in args.region.split(","))
        run_receiver(args.outdir, {"left": left, "top": top,
                                   "width": width, "height": height}, args.timeout)
        return 0

    # -- 驱动模式：一个进程开一边，接收端截屏解出来的文件要和原文件逐字节一致 --
    tmp = tempfile.mkdtemp(prefix="qrgui-")
    data = bytes((i * 37 + 11) % 251 for i in range(1500))
    src = os.path.join(tmp, "界面联调.bin")
    with open(src, "wb") as fp:
        fp.write(data)
    outdir = os.path.join(tmp, "out")
    os.makedirs(outdir)
    print("原文件：%s（%d 字节，sha256 %s…）"
          % (src, len(data), hashlib.sha256(data).hexdigest()[:16]))

    env = dict(os.environ)
    sender = subprocess.Popen(
        [sys.executable, "-u", os.path.abspath(__file__), "--role", "sender",
         "--file", src, "--chunk", str(args.chunk), "--interval", str(args.interval),
         "--hold", str(args.hold), "--timeout", str(args.timeout)], env=env)
    receiver = subprocess.Popen(
        [sys.executable, "-u", os.path.abspath(__file__), "--role", "receiver",
         "--outdir", outdir, "--timeout", str(args.timeout)], env=env)

    try:
        rcode = receiver.wait(timeout=args.timeout + 30)
    except subprocess.TimeoutExpired:
        rcode = 2
        receiver.kill()
    sender.terminate()
    try:
        sender.wait(timeout=10)
    except subprocess.TimeoutExpired:
        sender.kill()

    files = [f for f in os.listdir(outdir) if not f.endswith((".qrtpart", ".qrtstate"))]
    print("\n接收端退出码 %d，输出目录：%s" % (rcode, files))
    if rcode != 0 or not files:
        print("✖ 失败：接收端没能在超时前完成")
        return 1
    saved = os.path.join(outdir, files[0])
    got = open(saved, "rb").read()
    if got != data:
        print("✖ 失败：文件内容不一致（收到 %d 字节，期望 %d 字节）" % (len(got), len(data)))
        return 1
    leftovers = [f for f in os.listdir(outdir) if f.endswith((".qrtpart", ".qrtstate"))]
    if leftovers:
        print("✖ 失败：完成后残留临时文件 %s" % leftovers)
        return 1
    print("✔ 通过：两个界面联调成功，还原文件逐字节一致（%d 字节）" % len(got))
    return 0


if __name__ == "__main__":
    sys.exit(main())
