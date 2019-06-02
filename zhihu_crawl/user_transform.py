#!/usr/bin/env python3
# coding=utf-8
"""抓取到用户格式转换
json -> 固定格式行(分号分割)
"""
import json

fp = open("users.txt", 'w')

with open('zhihu-users.txt', 'r') as f:
    for line in f:
        r = json.loads(line.strip())
        u = []
        for k in r:
            u.append(k)
            u.append(str(r[k]['follower_id']))
            u.append(r[k]['name'])
            u.append(r[k]['url_token'])
            u.append(str(r[k]['gender']))
            u.append(str(r[k]['follower_count']))
            row = ';'.join(u)
        fp.write("%s\n" % row)
fp.close()