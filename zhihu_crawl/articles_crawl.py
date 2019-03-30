#!/usr/bin/env python3
# coding=utf-8
import os
import json
import time
import random

import brotli
import requests


api_url = "https://www.zhihu.com/api/v4/members/{member_name}/articles"

params = {
    "include": "data[*].comment_count,suggest_edit,is_normal,thumbnail_extra_info,thumbnail,can_comment,comment_permission,admin_closed_comment,content,voteup_count,created,updated,upvoted_followees,voting,review_info,is_labeled,label_info;data[*].author.badge[?(type=best_answerer)].topics",
    "offset": "0",
    "limit": "20"
}

req_headers = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Cookie": '_xsrf=SE63x3urTp9rKORk2yxD6QlnJvaQHJ8g; _zap=3058a75e-6510-4430-bba4-b64283308703; d_c0="APBl_DgUGA6PThP3D96P6Ee2vv93uOKxWy4=|1534914082"; q_c1=54f5a04b3a7647da9722267e04c33762|1534915940000|1534915940000; l_cap_id="NGZlNGJkMDgxZGVlNDI4Njk4NDBlYzdkY2Q5YTdkNGE=|1547598703|c9cc541f11d88d468dc24d72cfe6ea1b30f6ec36"; r_cap_id="MjMwODBiNTI2MTJjNGI5NmEwNWYyMDQ1NTU0NjBkMTI=|1547598703|06b461571a1d538270e3f930b3ac073525fcc1e8"; cap_id="Mjc2ZGZhMDQzMmU0NDg2YWEzODYyZTJkNjEzMWZhYmE=|1547598703|1daee2e8ec44f14c8656b1df6f588bcc7896cad0"; __utmz=155987696.1547599589.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utma=155987696.1529523650.1547599589.1547599589.1547606092.2; tgw_l7_route=116a747939468d99065d12a386ab1c5f',
    'Host': 'www.zhihu.com',
    "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36'
}

session = requests.Session()
code_errors = []

def get_articles(api_url, member_name):
    """获取指定用户的文章内容
    仅获取第一页
    """
    offset = 0
    limit = 20
    params['offset'] = str(offset)
    params['limit'] = str(limit)
    rs = get_api_results(api_url.format(member_name=member_name), params, req_headers)
    time.sleep(random.randint(1, 3))
    if rs:
        print("user {} articles success! 总条数: {}".format(member_name, rs['paging']['totals']))
        if rs['data']:
            print("返回条数: {}".format(len(rs['data'])))
            return rs['data']
        else:
            print("data is empty!")
    else:
        print("user {} failed!".format(member_name))

def get_api_results(api_url, params, headers):
    try:
        r = session.get(api_url,
                        params=params,
                        headers=req_headers,
                        timeout=10)
        if r.status_code == 200:
            # print("user {} success.".format(member_name))
            if 'Content-Encoding' in r.headers and r.headers['Content-Encoding'] == 'br':
                # print('br decode.')
                # Google brotli无损压缩算法: https://github.com/google/brotli
                # https://pypi.org/project/Brotli
                r_text = brotli.decompress(r.content)
                info = json.loads(r_text)
            else:
                info = r.json()
            return info
        else:
            print("status code: %d" % r.status_code)
            code_errors.append(r.status_code)
    except Exception as e:
        print("Error! {}".format(e))
    return None

user_tokens = {}
with open('zhihu-users.txt', 'r') as f:
    for line in f:
        user_info = json.loads(line.strip())
        for user_token, followe_info in user_info.items():
            if user_token not in user_tokens:
                user_tokens[user_token] = 0
            if followe_info['url_token'] not in user_tokens:
                user_tokens[followe_info['url_token']] = 0

print("整理完毕, 共有用户个数: {}".format(len(user_tokens)))
if os.path.isfile('zhihu-articles.txt'):
    f = open('zhihu-articles.txt', 'a')
    print("继续追加文件.")
else:
    f = open('zhihu-articles.txt', 'w')
    print("create article file.")
users_processed = []
if os.path.isfile('users-processed.break'):
    with open('users-processed.break', 'r') as fb:
        users_processed = json.loads(fb.read())
    print("已处理用户数: {}".format(len(users_processed)))

try:
    for member_name in user_tokens:
        if member_name in users_processed:
            print("{} 已处理, 跳过.".format(member_name))
            continue
        rs = get_articles(api_url, member_name)
        if rs:
            article_info = {
                member_name: rs
            }
            f.write(json.dumps(article_info))
            f.write("\n")
        else:
            print("用户: {} 没有文章.".format(member_name))
        users_processed.append(member_name)
        with open('users-processed.break', 'w') as fb:
            fb.write(json.dumps(users_processed))
        print("已处理用户数: {}".format(len(users_processed)))
        time.sleep(0.5)
        if code_errors and len(code_errors) > 3:
            print("errors: {} 次数过多! ".format(code_errors))
            f.close()
            session.close()
            print("exit.")
            break
except KeyboardInterrupt:
    print("Ctrl+C.")
    session.close()
    f.close()
    print("exit.")
