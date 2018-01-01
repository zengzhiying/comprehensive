#!/usr/bin/env python
# coding=utf-8
"""微信跳一跳执行脚本
首先应该启动adb服务并且手机开启USB调试连接成功
执行大致流程:
    1. adb调用手机截图并自动发送至本地
    2. 使用opencv读取截图并和事先截取好的小人模板进行匹配确定起跳点坐标
    3. 将截图通过matplotlib模块显示输出并绑定鼠标点击事件, 当鼠标点击目标点时获取到落点坐标
    4. 通过起点和目标点计算欧式距离, 然后尝试找出按住屏幕起跳的时间 (先考虑简单的正比关系, 存在比较准确的正比关系即: 时间(ms) = 1.31 * 距离)
    5. 通过时间生成屏幕长按指令发送至手机执行跳一跳
    6. 然后不断按照上面步骤往复循环, 实现连续的跳一跳动作
设计思路参考自: https://github.com/wangshub/wechat_jump_game 尊重原创, 表示感谢!
"""
import sys
import os
import time

import cv2
import numpy as np
import matplotlib.pyplot as plt
reload(sys)
sys.setdefaultencoding('utf-8')

# plt.ion()
villain_coordinate = {}
is_quit = []

def pull_screenshot():
    """调用手机截图并拉取截图到本地
    """
    start_time = time.time()
    os.system('adb shell screencap -p /sdcard/game_screenshots.png')
    os.system('adb pull /sdcard/game_screenshots.png .')
    end_time = time.time()
    print("截图pull完毕. 耗时: {}s".format(round(end_time - start_time, 2)))

def get_draw_image_villain_box(image, template_image):
    """从截图大图中以小人为模板进行搜索
    搜索方式类似于最原始的滑动窗口比对, 并将区域使用方框进行框选绘制
    Args:
        image: 大图矩阵
        template_image: 模板矩阵
    Returns:
        匹配完毕返回大图加框选完的矩阵和小人焦点坐标组成的元组
    """
    match_result = cv2.matchTemplate(image, template_image, cv2.TM_SQDIFF)  # 匹配方式: 平方差匹配
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(match_result)

    template_size = template_image.shape[:2]
    # 绘制方框
    cv2.rectangle(image,
                  (min_loc[0], min_loc[1]),  # 起点坐标(左上)
                  (min_loc[0] + template_size[1], min_loc[1] + template_size[0]), # 区域终点坐标(右下)
                  (255, 0, 0), # 绘制红色
                  4)

    # 小人底座点坐标 注意: 是起始横坐标加上小人宽度除以2, 先除再加
    center_point = min_loc[0] + template_size[1]/2, min_loc[1] + template_size[0]

    return image, center_point

def onclick(event):
    """点击鼠标响应事件
    """
    print('button={}, x={}, y={}, xdata={}, ydata={}'.format(event.button,  # 按下的按钮
                                                             event.x,  # 图片宽度
                                                             event.y,  # 高度
                                                             event.xdata, # 鼠标点击横坐标
                                                             event.ydata)) # 点击纵坐标
    # click_coordinate.update({'x': event.xdata, 'y': event.ydata})
    # 计算距离
    target_location = [event.xdata, event.ydata]
    villain_location = [villain_coordinate['x'], villain_coordinate['y']]
    distance = euclidean_distance(villain_location, target_location)
    print("当前离目标距离为: {}".format(distance))
    # 按下时间估计
    press_time = int(distance * 1.31)
    # 开始执行跳动作
    jump(press_time)
    # plt.pause(3)
    time.sleep(0.5)
    plt.close()  # 关闭窗口

def onbutton(event):
    print(event.key)
    if event.key == 'q':
        print("触发q动作, 即将停止进程.")
        is_quit.append('stop')


def euclidean_distance(x1, x2):
    """欧式距离计算
    Args:
        x1: 列表类型的多维向量,元素为数值型 如: [12, 16, 23]
        x2: 和x1维度相同的列表 如: [11, 15, 25]
    Returns:
        返回欧式距离的计算结果 如上面的输入返回应为: 2.45
    """
    v1 = np.array(x1)
    v2 = np.array(x2)
    distance = np.sum(np.square(v1 - v2))
    distance = distance ** 0.5
    return distance

def jump(press_time):
    start_time = time.time()
    # print('adb shell input swipe 900 1700 900 1700 {}'.format(press_time))
    os.system('adb shell input swipe 900 1700 900 1700 {}'.format(press_time))
    end_time = time.time()
    print("跳命令执行完毕. 耗时: {}s".format(round(end_time - start_time, 2)))


if __name__ == '__main__':
    # 处理小人图片
    # scale = 0.25  # 缩小图片, 减少性能压力
    villain_image = cv2.imread('villain.png')
    # 缩放图片
    # villain_image = cv2.resize(villain_image, (0, 0), fx=scale, fy=scale)
    villain_size = villain_image.shape[:2]
    print("初始化小人成功！大小: {}".format(villain_size))
    while True:
        # 截取手机图片并拉取至本地
        pull_screenshot()
        # 处理并搜索截图中的小人
        screenshot_image = cv2.imread('game_screenshots.png')
        # screenshot_image = cv2.resize(screenshot_image, (0, 0), fx=scale, fy=scale)
        screenshot_box_image = get_draw_image_villain_box(screenshot_image, villain_image)
        # 更新坐标字典
        villain_coordinate.update({'x': screenshot_box_image[1][0], 'y': screenshot_box_image[1][1]})
        # 初始化matplotlib面板
        fig = plt.figure()
        # 将截图及绘制结果显示出来
        image_draw = plt.imshow(screenshot_box_image[0])
        # 绑定鼠标事件 button_press_event: 鼠标按钮被按下 触发动作: onclick函数
        fig.canvas.mpl_connect('button_press_event', onclick)
        # 绑定按键退出事件
        fig.canvas.mpl_connect('key_press_event', onbutton)
        plt.show()
        if is_quit:
            print('done.')
            break

