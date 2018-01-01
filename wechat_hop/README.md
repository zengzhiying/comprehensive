# 使用脚本配合点击玩微信跳一跳游戏
## 运行平台: windows

> 需要的依赖和准备步骤大致如下:
1. adb驱动工具正常安装并启动服务
2. 手机开启开发者选项->USB调试并确定授权
然后执行`adb devices`和`adb get-state`确定可以看到设备并且状态为device表示正常
3. python环境安装, 并且有以下模块:
    opencv python模块 cv2
    numpy
    matplotlib
4. 手机确定开始游戏, 然后执行python -u hop.py启动进行, 然后即可开始玩游戏
游戏中按q键, 然后点击完最后一次可以退出程序
