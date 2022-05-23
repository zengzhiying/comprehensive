#!/usr/bin/env python3
# coding=utf-8
import os
import sys
import time
import base64
import struct

import qrcode
from qrcode.image.styles.colormasks import QRColorMask, SolidFillColorMask
import matplotlib.pyplot as plt

"""先运行后再启动录屏工具，提前设置区域录屏, 识别速度更快
"""

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("输入文件名!")
        sys.exit(-1)

    filename = sys.argv[1]
    if not os.path.isfile(filename):
        print("文件不存在!")
        sys.exit(-1)

    file_size = os.path.getsize(filename)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        # box_size=1000,
        border=4,
    )

    plt.figure(facecolor='black',figsize=(10, 8))
    # plt.set_cmap('binary')
    # mgr = plt.get_current_fig_manager()
    # mgr.window.wm_geometry("+0-0")
    show_time = 0.1
    buf_size = 1500

    total_qr = file_size // buf_size + 1

    print("文件大小: {}, 需要张数: {}".format(file_size, total_qr))

    qr.add_data("start|{}".format(total_qr))
    qr.make(fit=True)
    img = qr.make_image(color_mask=SolidFillColorMask(back_color=(255, 255, 255),
                                                      front_color=(0, 0, 0)))
    # img.show()
    plt.axis('off')
    plt.imshow(img)
    plt.pause(10)

    plt.clf()
    qr.clear()

    with open(filename, 'rb') as f:
        buf = f.read(buf_size)
        i = 0
        while buf:
            print(len(buf))
            write_row = base64.b64encode(struct.pack('<I', i) + buf)
            qr.add_data(write_row)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white", front_color='black')

            plt.axis('off')
            plt.imshow(img)

            if len(buf) < buf_size:
                show_time = 1
            
            plt.pause(show_time)
            plt.clf()

            qr.clear()

            buf = f.read(buf_size)

            i += 1


    print("exit")


    qr.version = 1
    qr.add_data("end")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    plt.axis('off')
    plt.imshow(img)
    plt.pause(10)

    plt.clf()
    qr.clear()

    plt.close()

