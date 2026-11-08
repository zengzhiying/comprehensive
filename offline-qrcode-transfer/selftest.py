#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py —— 本地自测（不需要 Windows、不需要摄像头、不需要真的两台机器）

跑法：
    python selftest.py            # 全部测试（端到端那部分需要图形环境）
    xvfb-run -a python selftest.py   # 无显示器的 Linux 上这样跑
    python selftest.py --no-gui   # 只跑不依赖界面的部分

覆盖：
    1. 协议解析：各种畸形帧都必须被拒掉
    2. 接收状态机：正常、重复帧、缺包停收、手动续传、接收端重启续传、
       参数冲突、缺包时收到结束帧、内容被篡改、空文件、末包不足
    3. 二维码编解码往返：发送端真实帧 → 画成图 → 解码 → 文本必须一字不差
    4. 抗压缩退化：模拟远程桌面的缩放/JPEG 压缩，看各分包大小的识别率
    5. 端到端：真的把发送端界面跑起来，截屏解码，还原文件并逐字节比对
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import receiver_windows as R
import sender_windows as S

PASS = 0
FAIL = 0
FAILURES = []


def check(cond, message):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(message)
        print("    ✖ %s" % message)


def section(title):
    print("\n=== %s ===" % title)


def silent_log(*_args, **_kwargs):
    pass


class LogCollector:
    def __init__(self):
        self.lines = []

    def __call__(self, message, level="info"):
        self.lines.append((level, message))

    def has(self, keyword):
        return any(keyword in msg for _lvl, msg in self.lines)


def make_file(directory, name, data):
    path = os.path.join(directory, name)
    with open(path, "wb") as fp:
        fp.write(data)
    return path


def render_qr(matrix, scale=8, quiet=4):
    """把模块矩阵画成 PIL 图像（白底黑块），模拟发送端屏幕上的样子。"""
    from PIL import Image
    n = len(matrix)
    side = (n + quiet * 2) * scale
    img = Image.new("L", (side, side), 255)
    px = img.load()
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if not dark:
                continue
            x0 = (c + quiet) * scale
            y0 = (r + quiet) * scale
            for y in range(y0, y0 + scale):
                for x in range(x0, x0 + scale):
                    px[x, y] = 0
    return img


# ---------------------------------------------------------------------------
# 1. 协议解析
# ---------------------------------------------------------------------------

def test_parse():
    section("1. 协议解析")
    session = "a1b2c3d4e5f60718"
    good_start = S.build_start_frame(session, 0, 10, 100, 950, "报表.xlsx")
    good_data = S.build_data_frame(session, 3, b"\x01\x02hello")
    good_end = S.build_end_frame(10, 950, "ab" * 32, "报表.xlsx")

    parsed = R.parse_frame(good_start)
    check(parsed and parsed["kind"] == "S" and parsed["total"] == 10
          and parsed["file_name"] == "报表.xlsx", "起始帧应能正常解析（含中文文件名）")
    parsed = R.parse_frame(good_data)
    check(parsed and parsed["kind"] == "D" and parsed["index"] == 3
          and parsed["payload"] == b"\x01\x02hello" and parsed["crc_ok"],
          "数据帧应能正常解析且校验通过")
    parsed = R.parse_frame(good_end)
    check(parsed and parsed["kind"] == "E" and parsed["sha256"] == "ab" * 32,
          "结束帧应能正常解析")

    bad_cases = [
        ("完全不是二维码内容", "随便一段文字"),
        ("版本号不对", good_data.replace("QRT1", "QRT9")),
        ("帧类型未知", good_data.replace("|D|", "|X|")),
        ("字段个数不对", "QRT1|D|1|abcd"),
        ("序号不是数字", "QRT1|D|abc|00000000|AAAA"),
        ("序号为负", "QRT1|D|-1|00000000|AAAA"),
        ("校验码长度不对", "QRT1|D|1|abcd|AAAA"),
        ("内容不是合法 base64", "QRT1|D|1|00000000|!!!!"),
        ("起始帧缺字段", "QRT1|S|sess|0|10|100"),
        ("起始帧总包数为 0", S.build_start_frame(session, 0, 0, 100, 950, "a")),
        ("起始帧分包为 0", S.build_start_frame(session, 0, 10, 0, 950, "a")),
        ("结束帧 sha256 长度不对", "QRT1|E|10|950|abcd|QQ=="),
        ("空字符串", ""),
    ]
    for label, text in bad_cases:
        check(R.parse_frame(text) is None, "畸形帧必须被拒：%s" % label)

    # 起始帧/结束帧的末尾 crc32：改动内容而没改校验码，必须整帧拒掉
    tampered_start = good_start.replace("|10|100|", "|11|100|")
    check(R.parse_frame(tampered_start) is None, "起始帧内容被改动（crc 没跟着改）必须整帧拒绝")
    tampered_end = good_end.replace("|10|950|", "|10|951|")
    check(R.parse_frame(tampered_end) is None, "结束帧内容被改动（crc 没跟着改）必须整帧拒绝")

    # 数据帧字段顺序：QRT1|D|<会话号>|<序号>|<crc32>|<b64数据>
    parts = good_data.split("|")
    check(len(parts) == 6 and parts[2] == session,
          "数据帧必须带会话号（防止换文件后数据串台）")

    # CRC 覆盖会话号和序号：改任何一个而没改校验码，都必须判为 crc_ok=False
    tampered = "|".join([parts[0], parts[1], parts[2], "99", parts[4], parts[5]])
    parsed = R.parse_frame(tampered)
    check(parsed is not None and parsed["crc_ok"] is False,
          "改过序号但校验码没跟着改，必须判为校验失败")
    tampered = "|".join([parts[0], parts[1], "ffffffffffffffff", parts[3], parts[4], parts[5]])
    parsed = R.parse_frame(tampered)
    check(parsed is not None and parsed["crc_ok"] is False,
          "改过会话号但校验码没跟着改，必须判为校验失败")

    # 内容被改
    tampered = S.build_data_frame(session, 3, b"\x01\x02hellp")
    check(R.parse_frame(tampered)["crc_ok"] is True, "内容改了但 crc 重算，应判为合法（模拟对端就是发了别的数据）")
    body = parts[5]
    flipped = "A" if body[0] != "A" else "B"
    tampered = "|".join([parts[0], parts[1], parts[2], parts[3], parts[4], flipped + body[1:]])
    check(R.parse_frame(tampered)["crc_ok"] is False, "内容被改动，校验必须失败")

    check(R.sanitize_file_name("../../windows/system32/evil.exe") == "evil.exe",
          "文件名必须去掉路径")
    check(R.sanitize_file_name("a:b*c?.txt") == "a_b_c_.txt", "文件名里的非法字符要替换掉")
    check(R.sanitize_file_name("") == "received.bin", "空文件名要有兜底")


# ---------------------------------------------------------------------------
# 2. 接收状态机
# ---------------------------------------------------------------------------

def make_transfer(directory, name, data, chunk):
    path = make_file(directory, name, data)
    return S.Transfer(path, chunk)


def test_protocol_consistency():
    """随机参数下：发送端构造的帧，接收端必须原样解析回来。"""
    section("1b. 协议一致性（发送端构造 ↔ 接收端解析）")
    import random
    names = ["报表.xlsx", "a b c.bin", "中文 名字（含空格）.dat", "no_ext",
             "emoji😀.bin", "UPPER.TXT", "-" * 60 + ".log"]
    bad = 0
    for _ in range(300):
        total = random.randint(1, 999999)
        start_index = random.randint(0, total - 1)
        chunk = random.randint(1, 1731)
        size = random.randint(0, 10 ** 9)
        name = random.choice(names)
        frame = S.build_start_frame("0123456789abcdef", start_index, total, chunk, size, name)
        parsed = R.parse_frame(frame)
        if not parsed or parsed["kind"] != "S" or (parsed["session"], parsed["start_index"],
                                                   parsed["total"], parsed["chunk_size"],
                                                   parsed["file_size"], parsed["file_name"]) \
                != ("0123456789abcdef", start_index, total, chunk, size, name):
            bad += 1
        payload = bytes(random.getrandbits(8) for _ in range(random.randint(0, 400)))
        index = random.randint(0, 999999)
        parsed = R.parse_frame(S.build_data_frame("0123456789abcdef", index, payload))
        if not parsed or parsed["index"] != index or parsed["payload"] != payload \
                or not parsed["crc_ok"]:
            bad += 1
        sha = "%064x" % random.getrandbits(256)
        parsed = R.parse_frame(S.build_end_frame(total, size, sha, name))
        if not parsed or (parsed["total"], parsed["file_size"], parsed["sha256"],
                          parsed["file_name"]) != (total, size, sha, name):
            bad += 1
    check(bad == 0, "300 组随机参数的三类帧都应原样往返（失败 %d 组）" % bad)


def test_state_machine():
    section("2. 接收状态机")

    tmp = tempfile.mkdtemp(prefix="qrselftest-")
    try:
        # --- 2.1 正常流程 ---
        data = os.urandom(2500)
        outdir = os.path.join(tmp, "case1")
        os.makedirs(outdir)
        transfer = make_transfer(tmp, "a.bin", data, 400)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        for i in range(transfer.total):
            core.feed(transfer.frame(i))
        result = core.feed(transfer.end_frame())
        check(result["status"] == "completed", "正常流程应当完成（实际 %s）" % result["status"])
        saved = result.get("path")
        check(saved and os.path.exists(saved), "完成后应生成文件")
        check(saved and open(saved, "rb").read() == data, "还原出的文件必须和原文件逐字节一致")
        check(not any(f.endswith((".qrtpart", ".qrtstate")) for f in os.listdir(outdir)),
              "完成后不该留下临时文件")

        # --- 2.2 重复帧去重 ---
        outdir = os.path.join(tmp, "case2")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        for i in range(transfer.total):
            core.feed(transfer.frame(i))
            core.feed(transfer.frame(i))          # 每包都重复扫到一次
            r = core.feed(transfer.frame(i))
            check(r["status"] == "duplicate", "同一包重复出现必须判为重复（第 %d 包）" % i)
        result = core.feed(transfer.end_frame())
        check(result["status"] == "completed", "有重复帧也应正常完成")
        check(open(result["path"], "rb").read() == data, "重复帧不能污染数据")

        # --- 2.3 缺包 → 停收 → 手动续传 ---
        outdir = os.path.join(tmp, "case3")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        missing = 3
        for i in range(transfer.total):
            if i == missing:
                continue                          # 模拟这一帧没扫到
            r = core.feed(transfer.frame(i))
            if i > missing:
                check(r["status"] == "gap", "缺包之后的数据必须被拒收（第 %d 包）" % i)
        check(core.status == R.STATUS_GAP, "缺包后状态应为 gap")
        check(core.gap_expected == missing, "应停在缺失的序号上（期望 %d，实际 %s）"
              % (missing, core.gap_expected))
        # 操作员把发送端起始序号改成 3 重发
        r = core.feed(transfer.start_frame(missing))
        check(r["status"] == "resumed", "重发起始帧后应进入续传（实际 %s）" % r["status"])
        check(core.status == R.STATUS_RECEIVING, "续传后应恢复接收")
        for i in range(missing, transfer.total):
            core.feed(transfer.frame(i))
        result = core.feed(transfer.end_frame())
        check(result["status"] == "completed", "续传后应当完成（实际 %s）" % result["status"])
        check(open(result["path"], "rb").read() == data, "续传还原的文件必须一致")

        # --- 2.4 缺包时收到结束帧：必须报缺包且绝不写文件 ---
        outdir = os.path.join(tmp, "case4")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        for i in range(1, transfer.total):
            core.feed(transfer.frame(i))
        result = core.feed(transfer.end_frame())
        check(result["status"] == "incomplete", "缺包时收到结束帧应报 incomplete（实际 %s）"
              % result["status"])
        check(not any(f == transfer.file_name for f in os.listdir(outdir)),
              "缺包时绝不能在输出目录里生成最终文件")
        check(os.path.exists(os.path.join(outdir, transfer.file_name + R.PART_SUFFIX)),
              "缺包时数据应保留在 .qrtpart 里以便续传")
        core.session.close()

        # --- 2.5 接收端重启后续传 ---
        outdir = os.path.join(tmp, "case5")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        for i in range(0, transfer.total // 2):
            core.feed(transfer.frame(i))
        core.session.save_state(force=True)
        core.session.close()
        # 模拟程序重启：全新 core，只靠磁盘上的 .qrtstate 恢复
        core2 = R.ReceiverCore(outdir, log=silent_log)
        core2.outdir = outdir
        core2.feed(transfer.start_frame(transfer.total // 2))
        check(core2.session is not None and core2.session.count == transfer.total // 2,
              "重启后应能从 .qrtstate 恢复已收进度（实际 %s 包）"
              % (core2.session.count if core2.session else None))
        check(core2.session.expected == transfer.total // 2,
              "重启后应继续等第 %d 包" % (transfer.total // 2))
        for i in range(transfer.total // 2, transfer.total):
            core2.feed(transfer.frame(i))
        result = core2.feed(transfer.end_frame())
        check(result["status"] == "completed", "重启后续传应当完成")
        check(open(result["path"], "rb").read() == data, "重启续传还原的文件必须一致")

        # --- 2.6 参数冲突（同名文件但内容不同）---
        outdir = os.path.join(tmp, "case6")
        os.makedirs(outdir)
        asked = {"count": 0}
        core = R.ReceiverCore(outdir, log=silent_log,
                              on_conflict=lambda info: (asked.__setitem__("count", asked["count"] + 1), True)[1])
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        core.feed(transfer.frame(0))
        core.session.save_state(force=True)
        # 同名文件、同样的大小和分包，但内容不同（会话号不同）
        other_session = hashlib.sha256(b"another content").hexdigest()[:16]
        other_start = S.build_start_frame(other_session, 0, transfer.total,
                                          transfer.chunk_size, transfer.file_size,
                                          transfer.file_name)
        r = core.feed(other_start)
        check(asked["count"] == 1, "内容变了必须询问是否丢弃旧进度")
        check(r["status"] == "started", "确认丢弃后应按新传输开始（实际 %s）" % r["status"])

        # --- 2.7 数据被篡改（校验码自洽但内容不是原文件的）---
        outdir = os.path.join(tmp, "case7")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        for i in range(transfer.total):
            if i == 2:
                core.feed(S.build_data_frame(transfer.session, i, os.urandom(400)))    # 内容被换掉
            else:
                core.feed(transfer.frame(i))
        result = core.feed(transfer.end_frame())
        check(result["status"] == "hash_mismatch",
              "整文件校验必须拦住被篡改的数据（实际 %s）" % result["status"])
        check(not any(f == "payload.bin" for f in os.listdir(outdir)),
              "校验失败时绝不能生成最终文件")

        # --- 2.8 空文件 ---
        outdir = os.path.join(tmp, "case8")
        os.makedirs(outdir)
        empty = make_transfer(tmp, "empty.bin", b"", 400)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(empty.start_frame(0))
        core.feed(empty.frame(0))
        result = core.feed(empty.end_frame())
        check(result["status"] == "completed", "空文件也应能完成（实际 %s）" % result["status"])
        check(os.path.getsize(result["path"]) == 0, "空文件还原出来应该还是 0 字节")

        # --- 2.9 末包不足一个分片 ---
        data9 = os.urandom(1000 + 7)
        outdir = os.path.join(tmp, "case9")
        os.makedirs(outdir)
        t9 = make_transfer(tmp, "x9.bin", data9, 100)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(t9.start_frame(0))
        check(t9.total == 11 and len(t9.payload(10)) == 7, "末包应为 7 字节")
        for i in range(t9.total):
            core.feed(t9.frame(i))
        result = core.feed(t9.end_frame())
        check(result["status"] == "completed", "末包不足也应完成")
        check(open(result["path"], "rb").read() == data9, "末包不足的文件必须一致")

        # --- 2.10 发送端从中间开始且接收端没有历史：最后必须报缺包 ---
        outdir = os.path.join(tmp, "case10")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(5))
        for i in range(5, transfer.total):
            core.feed(transfer.frame(i))
        result = core.feed(transfer.end_frame())
        check(result["status"] == "incomplete",
              "跳过的包没传，最后必须报缺包（实际 %s）" % result["status"])

        # --- 2.11 起始帧参数不自洽 ---
        outdir = os.path.join(tmp, "case11")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        bogus = S.build_start_frame("deadbeefdeadbeef", 0, 99, 400, 2500, "bad.bin")
        check(core.feed(bogus)["status"] == "bad_start", "总包数对不上必须拒绝起始帧")

        # --- 2.12 没收到起始帧就来数据 ---
        outdir = os.path.join(tmp, "case12")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        check(core.feed(transfer.frame(0))["status"] == "no_session",
              "没收到起始帧时数据帧应被拒（提示操作员重发起始帧）")

        # --- 2.13 换了文件但起始帧没扫到：另一个文件的数据必须被拒，不许串台 ---
        outdir = os.path.join(tmp, "case13")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        core.feed(transfer.frame(0))
        other_session = hashlib.sha256(b"another content").hexdigest()[:16]
        r = core.feed(S.build_data_frame(other_session, 1, transfer.payload(1)))
        check(r["status"] == "wrong_session",
              "另一个传输的数据帧必须被拒（实际 %s）" % r["status"])
        check(core.session.count == 1,
              "被拒的帧绝不能写进会话（应仍是 1 包，实际 %d）" % core.session.count)
        result = core.feed(transfer.end_frame())
        check(result["status"] == "incomplete",
              "串台被挡住之后，结束帧必须报缺包而不是保存（实际 %s）" % result["status"])
        core.session.close()

        # --- 2.14 整文件校验失败后必须清空进度，且重新完整传输要能成功 ---
        outdir = os.path.join(tmp, "case14")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        for i in range(transfer.total):
            if i == 2:
                core.feed(S.build_data_frame(transfer.session, i, os.urandom(400)))
            else:
                core.feed(transfer.frame(i))
        r = core.feed(transfer.end_frame())
        check(r["status"] == "hash_mismatch", "内容对不上必须判校验失败（实际 %s）" % r["status"])
        check(core.session.count == 0 and core.session.expected == 0,
              "校验失败后必须清空进度（否则重传的每一包都会被当成重复帧丢掉，"
              "日志里那句「重新完整传输」永远走不通）")
        core.feed(transfer.start_frame(0))
        for i in range(transfer.total):
            core.feed(transfer.frame(i))
        r = core.feed(transfer.end_frame())
        check(r["status"] == "completed",
              "校验失败后重新完整传一遍必须能成功（实际 %s）" % r["status"])
        check(r.get("path") and open(r["path"], "rb").read() == data,
              "重传出来的文件必须和原文件一致")

        # --- 2.15 参数冲突时选「保留旧进度」：不能崩，也不能继续收 ---
        outdir = os.path.join(tmp, "case15")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log, on_conflict=lambda info: False)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        core.feed(transfer.frame(0))
        core.session.save_state(force=True)
        other_session = hashlib.sha256(b"yet another").hexdigest()[:16]
        r = core.feed(S.build_start_frame(other_session, 0, transfer.total,
                                          transfer.chunk_size, transfer.file_size,
                                          transfer.file_name))
        check(r["status"] == "conflict_blocked",
              "选「保留旧进度」后本次传输应被挡下（实际 %s）" % r["status"])
        r = core.feed(transfer.frame(1))
        check(r["status"] == "no_session",
              "挡下之后再来数据帧应被平稳拒绝，不能抛异常（实际 %s）" % r["status"])
        check(os.path.exists(os.path.join(outdir, transfer.file_name + R.STATE_SUFFIX)),
              "选「保留」时旧进度必须还在")

        # --- 2.16 荒唐的起始帧参数必须被挡住，而且不能把状态搞坏 ---
        outdir = os.path.join(tmp, "case16")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        huge = S.build_start_frame("deadbeefdeadbeef", 0, 10 ** 25 - 1, 1, 10 ** 25 - 1, "h.bin")
        r = core.feed(huge)
        check(r["status"] == "bad_start", "超大参数必须被拒（实际 %s）" % r["status"])
        check(core.session is None and core.status == R.STATUS_IDLE,
              "被拒之后不能留下半初始化的会话")
        r = core.feed(transfer.start_frame(0))
        check(r["status"] == "started", "被拒之后必须还能正常开始新的传输（实际 %s）" % r["status"])
        core.session.close()

        # --- 2.17 状态文件被改过（位图比总包数长）也不能误判成收齐 ---
        outdir = os.path.join(tmp, "case17")
        os.makedirs(outdir)
        core = R.ReceiverCore(outdir, log=silent_log)
        core.outdir = outdir
        core.feed(transfer.start_frame(0))
        core.feed(transfer.frame(0))
        core.session.save_state(force=True)
        core.session.close()
        import json
        state_path = os.path.join(outdir, transfer.file_name + R.STATE_SUFFIX)
        raw = json.load(open(state_path, encoding="utf-8"))
        raw["bits"] = raw["bits"] + "////"          # 尾部塞一堆 1
        json.dump(raw, open(state_path, "w", encoding="utf-8"))
        loaded = R.Session.load(state_path)
        check(loaded is not None and loaded.count == 1,
              "载入进度必须以位图为准并裁掉多余的位（应为 1 包，实际 %s）"
              % (loaded.count if loaded else None))
        if loaded:
            loaded.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. 二维码编解码往返
# ---------------------------------------------------------------------------

def test_qr_roundtrip():
    section("3. 二维码编解码往返")
    if R.pyzbar is None and R.cv2 is None:
        print("    跳过：没有 pyzbar / opencv")
        return
    tmp = tempfile.mkdtemp(prefix="qrround-")
    try:
        decoder = R.QrDecoder()
        print("    解码器：%s" % " + ".join(decoder.backends))
        data = os.urandom(4000)
        for chunk in (100, 400, 800, 1500):
            transfer = make_transfer(tmp, "rt.bin", data, chunk)
            for label in (S.ECC_DEFAULT, list(S.ECC_LEVELS)[0]):
                transfer.ecc_label = label
                transfer.ecc = S.ECC_LEVELS[label]
                transfer._matrix_cache.clear()
                ok = 0
                total = min(transfer.total, 4)
                for i in range(total):
                    text = transfer.frame(i)
                    matrix, version = transfer.matrix(text)
                    img = render_qr(matrix, scale=6)
                    found = [r["text"] for r in decoder.decode(img)]
                    if text in found:
                        ok += 1
                check(ok == total, "分包 %d / %s：%d/%d 帧解码正确（QR v%d）"
                      % (chunk, label.split("（")[0], ok, total, version))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. 抗压缩退化（模拟远程桌面的缩放与有损压缩）
# ---------------------------------------------------------------------------

def test_degradation():
    section("4. 抗压缩退化（模拟 RDP 缩放 / JPEG 压缩）")
    if R.pyzbar is None and R.cv2 is None:
        print("    跳过：没有解码库")
        return
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="qrdegrade-")
    try:
        decoder = R.QrDecoder()
        data = os.urandom(30000)
        rows = []
        for chunk in (400, 600, 800, 1200, 1600):
            transfer = make_transfer(tmp, "dg.bin", data, chunk)
            matrix, version = transfer.matrix(transfer.frame(0))
            n = len(matrix) + 8
            base = render_qr(matrix, scale=max(3, 1000 // n))     # 约 1000 像素宽的二维码
            results = []
            for label, img in (
                ("原图", base),
                ("RDP缩放", base.resize((int(base.width * 0.75), int(base.height * 0.75)),
                                        Image.BILINEAR)),
                ("JPEG高", _jpeg(base, 75)),
                ("JPEG低", _jpeg(base, 35)),
                ("拍歪+压缩", _jpeg(base.rotate(3, expand=True, fillcolor=255), 45)),
            ):
                text = transfer.frame(0)
                found = [r["text"] for r in decoder.decode(img)]
                results.append("%s:%s" % (label, "OK" if text in found else "✖"))
            rows.append((chunk, version, n, results))
        print("    %-8s %-6s %-8s %s" % ("分包", "QR版本", "模块数", "各退化条件下的识别结果"))
        for chunk, version, n, results in rows:
            print("    %-8d v%-5d %-8d %s" % (chunk, version, n, "  ".join(results)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _jpeg(img, quality):
    from PIL import Image
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("L")


# ---------------------------------------------------------------------------
# 5. 端到端：真的把发送端界面跑起来 → 截屏 → 解码 → 还原文件
# ---------------------------------------------------------------------------

def _patch_dialogs():
    """自动化测试里绝不能弹出会阻塞的模态对话框，否则无人点击就是永久挂起。
    把对话框换成「记录下来并抛异常」，任何意外弹窗都会变成一次明确的测试失败。"""
    import tkinter.messagebox as mb
    dialogs = []

    def blocker(kind):
        def handler(title="", message="", **_kw):
            dialogs.append((kind, title, message))
            raise AssertionError("测试期间弹出了 %s 对话框：%s / %s" % (kind, title, message))
        return handler

    mb.showerror = blocker("showerror")
    mb.showinfo = blocker("showinfo")
    mb.showwarning = blocker("showwarning")
    mb.askyesno = lambda title="", message="", **_kw: (dialogs.append(("askyesno", title, message)), True)[1]
    return dialogs


def test_end_to_end(chunk=300, interval=0.3, hold=1.0, use_region=True):
    section("5. 端到端（真界面 + 真截屏 + 真解码）")
    dialogs = _patch_dialogs()
    if R.mss is None:
        print("    跳过：没有 mss")
        return
    if R.pyzbar is None and R.cv2 is None:
        print("    跳过：没有解码库")
        return
    try:
        import tkinter as tk
    except ImportError:
        print("    跳过：没有 tkinter")
        return

    tmp = tempfile.mkdtemp(prefix="qre2e-")
    outdir = os.path.join(tmp, "out")
    os.makedirs(outdir)
    data = os.urandom(2200)
    src = make_file(tmp, "端到端测试.bin", data)

    root = tk.Tk()
    app = S.SenderApp(root)
    app.transfer = S.Transfer(src, chunk)
    app.var_file.set(src)
    app.var_chunk.set(str(chunk))
    app.var_interval.set(str(interval))
    app.var_hold.set(str(hold))
    app.var_start.set("0")
    root.update()

    decoder = R.QrDecoder()
    core = R.ReceiverCore(outdir, log=silent_log)
    core.outdir = outdir

    source = R.ScreenSource()
    source.open()
    region = source.virtual_screen()
    if use_region:
        region = _find_qr_region(app, decoder, source, region)
    print("    截屏范围：%s" % region)
    print("    解码器：%s" % " + ".join(decoder.backends))

    try:
        # ---- 场景 A：一口气传完 ----
        app.begin()
        ok, elapsed = _pump_until_done(app, core, decoder, source, region, timeout=120)
        check(ok, "端到端场景 A：应当在超时前完成（实际状态 %s）" % core.status)
        if ok:
            check(core.saved_path and open(core.saved_path, "rb").read() == data,
                  "端到端场景 A：还原的文件必须逐字节一致")
            print("    场景 A 通过：%d 包 / %.1f 秒（约 %.1f 包/秒）"
                  % (app.transfer.total, elapsed, app.transfer.total / max(elapsed, 0.01)))

        # ---- 场景 B：中途丢一帧 → 报错停收 → 手动续传 ----
        for path in os.listdir(outdir):
            os.remove(os.path.join(outdir, path))
        core2 = R.ReceiverCore(outdir, log=silent_log)
        core2.outdir = outdir
        app.var_start.set("0")
        app.begin(0)
        drop_at = min(2, app.transfer.total - 2)
        ok, elapsed = _pump_until_done(app, core2, decoder, source, region,
                                       timeout=120, drop_index=drop_at)
        check(core2.status == R.STATUS_GAP and core2.gap_expected == drop_at,
              "端到端场景 B：丢帧后应停在缺包处（实际 %s / %s）"
              % (core2.status, core2.gap_expected))
        if core2.status == R.STATUS_GAP:
            print("    场景 B：成功模拟丢包，接收端停在缺第 %d 包" % drop_at)
            # 操作员把发送端起始序号改成缺的那个包，点「重发起始帧」
            app.var_start.set(str(drop_at))
            app.begin(drop_at)
            ok, elapsed2 = _pump_until_done(app, core2, decoder, source, region, timeout=120)
            check(ok, "端到端场景 B：续传后应当完成（实际 %s）" % core2.status)
            if ok:
                check(open(core2.saved_path, "rb").read() == data,
                      "端到端场景 B：续传还原的文件必须逐字节一致")
                print("    场景 B 通过：从第 %d 包续传后 %.1f 秒完成" % (drop_at, elapsed2))
    finally:
        source.close()
        try:
            app.on_close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def _find_qr_region(app, decoder, source, fallback):
    """自动定位二维码的外接框当截屏范围（顺便验证框选逻辑）。

    注意必须先等到数据阶段再定位：数据帧的二维码比起始帧大，
    按起始帧框出来的区域装不下数据帧，会漏帧——实际使用时框选也是同样的道理。
    """
    app.begin()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and app.phase != S.PHASE_DATA:
        app.root.update()
        time.sleep(0.05)

    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        app.root.update()
        image, _sig = source.grab(fallback)
        best = None
        for item in decoder.decode(image):
            if R.parse_frame(item["text"]) and item.get("rect"):
                x, y, w, h = item["rect"]
                if best is None or w * h > best[2] * best[3]:
                    best = (x, y, w, h)          # 取最大的那个（数据帧）
        if best is not None:
            x, y, w, h = best
            pad = 24
            return {"left": max(fallback["left"], fallback["left"] + x - pad),
                    "top": max(fallback["top"], fallback["top"] + y - pad),
                    "width": w + pad * 2, "height": h + pad * 2}
        time.sleep(0.1)
    print("    （没能自动定位二维码，改用整屏）")
    return fallback


def _pump_until_done(app, core, decoder, source, region, timeout=120, drop_index=None):
    """不断刷新发送端界面 + 截屏 + 解码 + 喂给状态机，直到完成为止。"""
    start = time.monotonic()
    confirmed = {}
    confirm_n = 2
    dropped_text = None
    while time.monotonic() - start < timeout:
        app.root.update()
        image, _sig = source.grab(region)
        for item in decoder.decode(image):
            text = item["text"].strip()
            parsed = R.parse_frame(text)
            if parsed is None:
                continue
            if drop_index is not None:
                if parsed["kind"] == "D" and parsed["index"] == drop_index:
                    dropped_text = text          # 这一帧整个丢掉，模拟完全没扫到
                if text == dropped_text:
                    continue
            seen = confirmed.get(text, 0) + 1
            if seen < confirm_n:
                confirmed[text] = seen
                continue
            confirmed[text] = 0
            core.feed(text)
        if core.status == R.STATUS_DONE:
            return True, time.monotonic() - start
        if core.status == R.STATUS_GAP and drop_index is not None:
            return False, time.monotonic() - start
        time.sleep(0.02)
    return False, time.monotonic() - start


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gui", action="store_true", help="跳过需要图形环境的端到端测试")
    args = parser.parse_args()

    test_parse()
    test_protocol_consistency()
    test_state_machine()
    test_qr_roundtrip()
    test_degradation()
    if not args.no_gui:
        test_end_to_end()

    print("\n" + "=" * 60)
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    if FAILURES:
        print("\n失败清单：")
        for item in FAILURES:
            print("  - %s" % item)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
