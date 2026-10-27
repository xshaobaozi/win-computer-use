"""agent 端（跨平台）—— 决策层。

这个包不 import 任何 Windows 专有模块，Mac / Linux / Windows 都能跑。
它只通过 WebSocket 与 server 通信，不知道对面是本机还是远端。
"""
