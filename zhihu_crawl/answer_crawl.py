#!/usr/bin/env python3
# coding=utf-8
"""指定用户问答抓取"""
import json
import time

import brotli
import requests

users = []
with open('answer-users.txt') as f:
    for u in f:
        users.append(u.strip())

print("users: {}".format(users))

api_url = "https://www.zhihu.com/api/v4/members/{}/answers"
params = {
    "include": "data[*].is_normal,admin_closed_comment,reward_info,is_collapsed,annotation_action,annotation_detail,collapse_reason,collapsed_by,suggest_edit,comment_count,can_comment,content,voteup_count,reshipment_settings,comment_permission,mark_infos,created_time,updated_time,review_info,question,excerpt,is_labeled,label_info,relationship.is_authorized,voting,is_author,is_thanked,is_nothelp,is_recognized;data[*].author.badge[?(type=best_answerer)].topics",
    "offset": "0",
    "limit": "20"
}

headers = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
    "Cookie": '_zap=500f3996-4cd3-4fdf-81ff-79c6563729af; _xsrf=IaQq4bDb2a9Xg5QoxnC0pY1FOHOgiwca; d_c0="ACCiU1C2Ig-PTqp_vuQe1cs4-Ym-oZpPjd8=|1552807531"; tst=r; q_c1=4dc9875e66524b3c876c3257551018ee|1552807829000|1552807829000; l_cap_id="YjJlZTBmNWM3ZmQwNDY1OGI2NTA2YjU2MWI4MjY2ZDU=|1552807950|1fdcb2c7acfe06e1c44a18aa67fded803633831f"; r_cap_id="MDlkMzZlNjk5NGMwNDRiNTkwMjNjNTc2MTgyNjMxZTU=|1552807950|886d795242a6b6f53bce83b6ea21cc679cfa27fd"; cap_id="YmFiZTIyYzI3ODdkNDZhZThmZjFkY2MzY2YxMmExMjI=|1552807950|b26919e95856343c1913fd5d9342c6fc374f00ea"; capsion_ticket="2|1:0|10:1553928728|14:capsion_ticket|44:NGNkMjlkMTFlNzVkNGNiMTgzNTg0NjI0MDc0OTRlMmU=|0c45bf93cb8fa0efa300240fb6f02297b0776af65340ac1fa2bd8584abed2c8c"; z_c0="2|1:0|10:1553928769|4:z_c0|92:Mi4xU2FPUkJBQUFBQUFBSUtKVFVMWWlEeVlBQUFCZ0FsVk5RV0NNWFFCbjZyMGtFSmx1YjdHU1FvWmZTV05EVnJzTDlB|3ece9a3d17a257b3ebc34990c881b08ac7858f902fffb77caef0026a2daecd5a"; tgw_l7_route=060f637cd101836814f6c53316f73463; __utma=155987696.585986723.1553930012.1553930012.1553930012.1; __utmb=155987696.0.10.1553930012; __utmc=155987696; __utmz=155987696.1553930012.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none)',
    "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.36'
}

session = requests.Session()

def get_user_answer(member_name):
    """获取用户指定偏移的回答"""
    try:
        r = session.get(api_url.format(member_name),
                        params=params,
                        headers=headers,
                        timeout=10)
        if r.status_code == 200:
            if 'Content-Encoding' in r.headers and r.headers['Content-Encoding'] == 'br':
                rs = json.loads(brotli.decompress(r.content))
            else:
                rs = r.json()
            return rs
        else:
            print("Status code: %d, user: %s" % (r.status_code, member_name))
    except Exception as e:
        print("Request Error! {}, user: {}".format(e, member_name))

# answers = get_user_answer(users[0])
# print(answers['paging']['totals'])
# print(len(answers['data']))
# users = ['qiu-mo-han-yu']
for user_name in users:
    print("开始抓取user name: %s" % user_name)
    params['offset'] = '0'
    # if user_name == 'xiao-jue-83':
    #     continue
    answers = get_user_answer(user_name)
    if not answers:
        print("用户: %s, 抓取失败！" % user_name)
        break
    number_total = answers['paging']['totals']
    print("用户: %s, 总回答条数: %d" % (user_name, number_total))
    number_write = 0
    print("偏移: 0 -> 20")
    with open('data/%s-answers.txt' % user_name, 'w') as f:
        if answers['data']:
            for info in answers['data']:
                row = {}
                row['title'] = info['question']['title']
                row['excerpt'] = info['excerpt']
                row['content'] = info['content']
                f.write(json.dumps(row))
                f.write("\n")
                f.flush()
                number_write += 1
                # print("写入: %d" % number_write)
        time.sleep(3)
        current_offset = 20
        while current_offset < number_total and current_offset <= 200:
            params['offset'] = str(current_offset)
            print("偏移: %d -> %d" % (current_offset, current_offset + 20))
            answers = get_user_answer(user_name)
            if not answers:
                print("用户: %s, 抓取失败！" % user_name)
                break
            if answers['data']:
                for info in answers['data']:
                    row = {}
                    row['title'] = info['question']['title']
                    row['excerpt'] = info['excerpt']
                    row['content'] = info['content']
                    f.write(json.dumps(row))
                    f.write("\n")
                    f.flush()
                    number_write += 1
            current_offset += 20
            time.sleep(5)
    print("用户: %s, 抓取完毕！ 总条数: %d" % (user_name, number_write))
