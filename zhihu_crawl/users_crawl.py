#!/usr/bin/env python3
# coding=utf-8
import os
import json
import time
import random

import brotli
import requests

member_name = "xiao-jue-83"
# 关注了
api_uri1 = "https://www.zhihu.com/api/v4/members/{member_name}/followees"
# 关注者
api_uri2 = "https://www.zhihu.com/api/v4/members/{member_name}/followers"

params = {
    "include": "data[*].answer_count,articles_count,gender,follower_count,is_followed,is_following,badge[?(type=best_answerer)].topics",
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

def get_member_follows(api_url, member_name):
    """获取指定用户的关注者或关注的人
    分页情况下最多获取10页
    """
    offset = 0
    limit = 20
    params['offset'] = str(offset)
    params['limit'] = str(limit)
    rs = get_api_results(api_url.format(member_name=member_name), params, req_headers)
    time.sleep(1)
    follows_infos = []
    if rs:
        print("user {} success!".format(member_name))
        if rs['data']:
            print("返回条数: {}".format(len(rs['data'])))
            follows_infos += rs['data']
            if rs['paging']['totals'] > 20:
                print("总条数: %d, 继续抓取." % rs['paging']['totals'])
                num_crawl = (rs['paging']['totals'] - 1) // 20
                num_crawl = 10 if num_crawl > 10 else num_crawl
                for i in range(num_crawl):
                    offset = (i + 1) * limit
                    params['offset'] = str(offset)
                    rs = get_api_results(api_url.format(member_name=member_name), params, req_headers)
                    if rs:
                        print("{} -> {} ok. {}".format(offset, limit, len(rs['data'])))
                        if rs['data']:
                            follows_infos += rs['data']
                    time.sleep(random.randint(1, 3))
        else:
            print("data is empty!")
    else:
        print("user {} failed!".format(member_name))
    return follows_infos

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
    except Exception as e:
        print("Error! {}".format(e))
    return None

if os.path.isfile('zhihu-users.txt'):
    f = open('zhihu-users.txt', 'a')
    print("文件存在, 继续追加.")
else:
    f = open('zhihu-users.txt', 'w')
    print("create data file.")

member_names = []
if os.path.isfile('zhihu-member-names.json'):
    with open('zhihu-member-names.json') as fc:
        member_names = json.loads(fc.read())

if member_names:
    member_name = member_names.pop(0)

try:
    while True:
        infos = get_member_follows(api_uri1, member_name)
        if infos:
            for info in infos:
                info['follower_id'] = 1
                user_info = {member_name: info}
                f.write(json.dumps(user_info))
                f.write("\n")
                member_names.append(info['url_token'])
                with open('zhihu-member-names.json', 'w') as fc:
                    fc.write(json.dumps(member_names))
        infos = get_member_follows(api_uri2, member_name)
        if infos:
            for info in infos:
                info['follower_id'] = 2
                user_info = {member_name: info}
                f.write(json.dumps(user_info))
                f.write("\n")
                member_names.append(info['url_token'])
                with open('zhihu-member-names.json', 'w') as fc:
                    fc.write(json.dumps(member_names))

        if member_names:
            print("names length: {}".format(len(member_names)))
            member_name = member_names.pop(0)
        else:
            print("member_names is empty! exit.")
            session.close()
            f.close()
            break
except KeyboardInterrupt:
    print("Ctrl+C close.")
    session.close()
    f.close()
    print("exit.")
