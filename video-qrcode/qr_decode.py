#!/usr/bin/env python3
# coding=utf-8
import sys
import base64
import struct

import cv2
import pyzbar.pyzbar as pyzbar

if __name__ == '__main__':
    video_name = '/home/share/20220427_144828.mp4'
    out_filename = 'lmbench-3.0-a9.tgz'
    step_size = 5
    cap = cv2.VideoCapture(video_name)
    if not cap.isOpened():
        print("Opened video: {} error!".format(video_name))
        sys.exit(-1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    print("码率: %g Hz" % fps)
    video_size = (cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                  cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print("size: {}".format(video_size))
    total_frame = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    print("总帧数: {}".format(total_frame))
    status, img = cap.read()
    frame_idx = 0
    qr_detector = cv2.QRCodeDetector()

    num = -1
    total_qr = 0
    file_size = 0

    of = open(out_filename, 'wb')

    while status:
        if frame_idx % step_size == 0:
            # data, bbox, qrimg = qr_detector.detectAndDecode(img)
            # print(data, bbox, qrimg)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            det = pyzbar.decode(gray)
            if det:
                data, rect = det[0].data, det[0].rect
                # print(data, rect)
                if data[:5] == b'start':
                    total_qr = int(data.decode().split('|')[1])
                    print("开始处理, 张数: %d" % total_qr)
                elif data == b'end':
                    print("处理完毕.")
                    break
                else:
                    try:
                        dec_data = base64.b64decode(data)
                    except Exception as e:
                        print("Base64 deocde error: {}".format(e))
                    else:
                        cur = struct.unpack('<I', dec_data[:4])[0]
                        if cur > num:
                            # if total_qr > 0 and total_qr - cur < 10:
                            #     # 接近最后1张 调小步长
                            #     step_size = 1
                            # print(cur, cur == num + 1)
                            if cur != num + 1:
                                print("miss!")
                                break
                            # print(data[4:].decode())
                            of.write(dec_data[4:])
                            print(cur, len(dec_data[4:]))
                            file_size += len(dec_data[4:])
                            num = cur
                        # else:
                        #     print("重复.")
            else:
                print("not decode.", det)


        status, img = cap.read()
        frame_idx += 1

    of.close()

    print("file size: {}".format(file_size))
